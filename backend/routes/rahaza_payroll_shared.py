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


# ── Q8 (keputusan owner 9 Nov 2026, "ikuti rekomendasi"): siapa melihat GAJI PER ORANG ─────────────────────
# Slip, rincian komponen, Excel/CSV/PDF per karyawan → HANYA peran penggajian (aturan yang SAMA dengan `_require_hr`:
# PAYROLL_HR_ROLES atau izin hr.manage/payroll.manage; keputusan 6 Nov — HR Manager & Staf HR tidak termasuk).
# Keuangan → total run + NILAI TRANSFER per karyawan (nama, rekening, gaji bersih) tanpa rincian komponen.
# Dulu gerbang slip juga meloloskan semua pemegang Portal SDM/Keuangan/Manajemen (staf HR, akuntansi, manajer
# produksi membaca 19 slip + Excel per orang).
PAYROLL_DETAIL_PERMS = ("*", "hr.manage", "payroll.manage")
PAYROLL_TRANSFER_PERMS = ("finance.manage", "fin.payment.manage", "fin.cash.manage")


def can_view_payroll_detail(user: dict | None) -> bool:
    """Boleh melihat rincian gaji per orang (slip, komponen, Excel per karyawan)?"""
    u = user or {}
    if (u.get("role") or "").lower() in PAYROLL_HR_ROLES:
        return True
    perms = u.get("_permissions") or []
    return any(p in perms for p in PAYROLL_DETAIL_PERMS)


def can_view_payroll_transfer(user: dict | None) -> bool:
    """Boleh melihat total run + nilai transfer per karyawan (Keuangan)? Peran penggajian juga boleh."""
    if can_view_payroll_detail(user):
        return True
    u = user or {}
    from core.roles import FINANCE_ROLES
    if (u.get("role") or "").lower() in FINANCE_ROLES:
        return True
    perms = u.get("_permissions") or []
    if any(p in perms for p in PAYROLL_TRANSFER_PERMS):
        return True
    from routes.shared import check_portal_access
    return bool(check_portal_access(u, "finance"))


def transfer_row(slip: dict, emp: dict | None = None) -> dict:
    """Baris transfer gaji untuk Keuangan: identitas + rekening + gaji bersih (tanpa komponen)."""
    e = emp or {}
    return {"id": slip.get("id"), "employee_id": slip.get("employee_id"),
            "employee_code": slip.get("employee_code") or e.get("employee_code") or "",
            "employee_name": slip.get("employee_name") or e.get("name") or "",
            "department": slip.get("department") or e.get("department") or "",
            "bank_name": e.get("bank_name") or "",
            "bank_account_number": e.get("bank_account_number") or e.get("bank_account") or "",
            "net_pay": float(slip.get("net_pay") or 0)}


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


def lwop_days_in_period(leaves: list, period_from: date, period_to: date, holiday_set: set,
                        off_weekdays=None) -> float:
    """Hari cuti tanpa gaji yang jatuh DI DALAM periode (Tahap 1, 2026-11-06).

    2026-11-06 (Tahap 2): hari kerja = SATU aturan `core.workdays` (bawaan 6 hari/minggu, bukan lagi
    Senin–Jumat). Mesin hitung slip TIDAK lagi memakai fungsi ini — potongan cuti tanpa gaji kini satu
    aturan dengan alpa (`rahaza_payroll_rules.classify_days`); fungsi dipertahankan untuk laporan/uji.
    Cuti setengah hari bernilai 0,5 per hari kerja; cuti lintas periode hanya dihitung bagian periode ini.
    """
    from core.workdays import DEFAULT_WORK_DAYS_PER_WEEK, off_weekdays_for, working_days_between
    off = off_weekdays if off_weekdays is not None else off_weekdays_for(DEFAULT_WORK_DAYS_PER_WEEK)
    total = 0.0
    for lv in leaves or []:
        try:
            start = max(period_from, _to_date(str(lv.get("from_date"))[:10]))
            end = min(period_to, _to_date(str(lv.get("to_date") or lv.get("from_date"))[:10]))
        except (TypeError, ValueError):
            log.warning("[payroll] cuti tanpa gaji %s: tanggal tidak valid — dilewati", lv.get("id"))
            continue
        weight = 0.5 if lv.get("is_half_day") else 1.0
        if start <= end:
            total += weight * len(working_days_between(start, end, off, holiday_set))
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# KASBON: SATU CICILAN PER BULAN HANYA UNTUK SATU RUN (Tahap 1, 2026-11-06)
# ═══════════════════════════════════════════════════════════════════════════════

async def kasbon_claimed_by_other_runs(db, employee_id: str, period_ym: str, kasbon_ids: list) -> dict:
    """{kasbon_id: nomor run} untuk kasbon yang potongan bulan `period_ym`-nya SUDAH ada di slip run
    lain yang belum dibatalkan (draft maupun final).

    Dulu dua run draft di bulan yang sama (mis. dua run mingguan) sama-sama memotong kasbon yang sama:
    karyawan menerima gaji kurang dua kali, sementara modul kasbon hanya mencatat satu potongan
    (dedupe periode saat finalisasi) ⇒ selisih tertinggal di Hutang Gaji. Bulan = BULAN GAJI
    (`rahaza_payroll_rules.payroll_month` = bulan `period_to`, M2 9 Nov 2026), sama dengan kunci dedupe kasbon."""
    if not kasbon_ids:
        return {}
    slips = await db.rahaza_payslips.find({
        "employee_id": employee_id,
        "$or": [{"period_to": {"$gte": f"{period_ym}-01", "$lte": f"{period_ym}-31"}},
                # slip lama tanpa period_to: bulan awal periode (perilaku sebelum M2)
                {"period_to": {"$exists": False}, "period_from": {"$gte": f"{period_ym}-01", "$lte": f"{period_ym}-31"}}],
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
    from routes.rahaza_payroll_rules import payroll_month
    period_ym = payroll_month(run.get("period_from"), run.get("period_to"))
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
# 2026-11-06 (Tahap 2) — mesin hitung disusun ulang mengikuti keputusan owner 6 Nov 2026
# (aturan murni di `rahaza_payroll_rules`, pajak di `rahaza_payroll_tax`):
#   · hari kerja = core.workdays (6 hari/minggu bawaan, libur Kalender Produksi)
#   · gaji bulanan/mingguan PRORATA masa kerja (join_date … tanggal keluar) & per versi tarif (kenaikan gaji
#     berlaku mulai tanggal tertentu), pembagi = hari kerja aktif periode
#   · potongan tidak masuk SATU aturan: alpa + izin/sakit/cuti tidak dibayar / tanpa pengajuan disetujui
#     (menggantikan LWOP terpisah); hari tanpa catatan absen TIDAK dipotong, hanya diperingatkan
#   · lembur hanya pengajuan disetujui / ditandai HR, pengali per hari dari Pengaturan Payroll
#   · bonus kehadiran hangus menurut Pengaturan Payroll
#   · BPJS & PPh21 (TER + perhitungan setahun Desember) untuk SEMUA skema, kumulatif per bulan pajak
#   · koreksi absensi pada periode yang sudah final → baris penyesuaian di run berikutnya

SYSTEM_WAGE_DEDUCTIONS = ("late", "absence", "absence_correction", "lwop")   # mengurangi upah (bukan titipan)
CORRECTION_LOOKBACK_DAYS = 93


def _round(v) -> int:
    return int(round(float(v or 0)))


async def _tax_history(db, emp_id: str, year: str, run_id: str | None) -> list:
    """Slip karyawan di tahun pajak `year` dari run LAIN yang tidak dibatalkan (draft maupun final)."""
    slips = await db.rahaza_payslips.find(
        {"employee_id": emp_id, "period_to": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"}},
        {"_id": 0, "run_id": 1, "period_to": 1, "gross_pay": 1, "deductions": 1, "bpjs_employer": 1,
         "tax": 1, "pay_scheme": 1}).to_list(400)
    slips = [s for s in slips if s.get("run_id") and s.get("run_id") != run_id]
    if not slips:
        return []
    ids = list({s["run_id"] for s in slips})
    live = {r["id"] for r in await db.rahaza_payroll_runs.find(
        {"id": {"$in": ids}, "status": {"$ne": "cancelled"}}, {"_id": 0, "id": 1}).to_list(len(ids))}
    return [s for s in slips if s["run_id"] in live]


def _slip_tax_figures(s: dict) -> dict:
    """Angka pajak satu slip lama/baru (slip sebelum Tahap 2 tidak punya `tax`)."""
    tax = s.get("tax") or {}
    by = {}
    for d in s.get("deductions") or []:
        t = (d.get("type") or "").lower()
        by[t] = by.get(t, 0.0) + float(d.get("amount") or 0)
    er = s.get("bpjs_employer") or {}
    taxable = tax.get("taxable_gross")
    if taxable is None:
        taxable = max(0.0, float(s.get("gross_pay") or 0) - sum(by.get(t, 0.0) for t in SYSTEM_WAGE_DEDUCTIONS))
    return {"tax_month": tax.get("tax_month") or str(s.get("period_to") or "")[:7],
            "taxable": float(taxable), "bpjs_base": float(tax.get("bpjs_base") or 0),
            "pph21": by.get("pph21", 0.0), "kes": by.get("bpjs_kesehatan", 0.0), "jht": by.get("bpjs_jht", 0.0),
            "jp": by.get("bpjs_jp", 0.0),
            "er": {k: float(er.get(k) or 0) for k in ("kes", "jht", "jp", "jkk", "jkm")}}


def pph21_line(*, pph_cfg: dict, figs: list, tax_month: str, taxable: float, jht_jp_this: float, emp: dict,
               scheme: str, pt: date, end: date | None) -> dict:
    """PPh21 satu slip — SATU rumus untuk mesin hitung slip dan penyesuaian slip (2026-11-09, H3).

    TER bulanan (PP 58/2023) atas bruto bulan pajak kumulatif (slip run lain di bulan yang sama dikurangkan),
    perhitungan setahun Pasal 17 di Desember / bulan terakhir bekerja (PMK 168/2023). `figs` = angka pajak slip
    run LAIN tahun itu (`_slip_tax_figures`). Return {amount, label, detail, warnings}."""
    from routes.rahaza_payroll_tax import has_tax_id, pph21_annual, pph21_ter_month, _pct
    month_prior = [f for f in figs if f["tax_month"] == tax_month]
    pm_taxable = sum(f["taxable"] for f in month_prior)
    pm_pph = sum(f["pph21"] for f in month_prior)
    ptkp = (emp.get("tax_ptkp") or "TK/0").upper()
    no_id = not has_tax_id(emp)
    ter = pph21_ter_month(pm_taxable + taxable, ptkp, pph_cfg, no_tax_id=no_id)
    pph = max(0, ter["tax"] - _round(pm_pph))
    detail = {**ter, "prior_withheld_month": _round(pm_pph), "ptkp_code": ptkp, "has_tax_id": not no_id}
    label = f"PPh21 TER {ter['category']} ({_pct(ter['rate'])})"
    warnings = []
    last_month = pt.month == 12 or bool(end and end.year == pt.year and end.month == pt.month and end <= pt)
    if scheme == "monthly" and pph_cfg.get("december_true_up") and last_month:
        months = {f["tax_month"] for f in figs} | {tax_month}
        ann = pph21_annual(sum(f["taxable"] for f in figs) + taxable,
                           sum(f["jht"] + f["jp"] for f in figs) + jht_jp_this,
                           ptkp, len(months), pph_cfg, no_tax_id=no_id)
        withheld = _round(sum(f["pph21"] for f in figs))
        due = ann["tax_year"] - withheld
        detail = {**detail, **ann, "method": "annual", "prior_withheld_year": withheld}
        label = "PPh21 perhitungan setahun" + (" (Desember)" if pt.month == 12 else " (bulan terakhir bekerja)")
        pph = max(0, due)
        if due < 0:
            detail["overpaid"] = -due
            warnings.append({"type": "pph21_overpaid",
                             "message": f"PPh21 setahun lebih potong Rp {-due:,.0f} — kembalikan ke karyawan lewat "
                                        "penyesuaian pendapatan.".replace(",", ".")})
    return {"amount": pph, "label": f"{label} — {ptkp}", "detail": detail, "warnings": warnings}


def slip_taxable(slip: dict, pph_cfg: dict, gross: float | None = None) -> float:
    """Bruto kena PPh21 sebuah slip = upah (bruto TERMASUK penyesuaian pendapatan − potongan terlambat/tidak masuk
    yang berlaku) + premi JKK/JKM/Kes perusahaan (bila setelan memasukkannya)."""
    g = float(slip.get("gross_pay") or 0) if gross is None else float(gross)
    wage_cut = sum(float(d.get("amount") or 0) for d in slip.get("deductions") or []
                   if (d.get("type") or "") in SYSTEM_WAGE_DEDUCTIONS)
    er = slip.get("bpjs_employer") or {}
    premiums = (float(er.get("jkk") or 0) + float(er.get("jkm") or 0) + float(er.get("kes") or 0)) \
        if pph_cfg.get("employer_premiums_taxable") else 0
    return max(0.0, g - wage_cut) + premiums


async def recompute_slip_pph21(db, slip: dict, emp: dict | None, *, run_id: str | None) -> dict:
    """Hitung ULANG baris PPh21 slip sesudah penyesuaian manual (tombol Adj / hitung ulang run) — 2026-11-09 (H3).

    Dulu `adjust_payslip` hanya menambah bruto: THR/bonus/rapel tidak pernah dipajaki (bulan itu maupun
    perhitungan setahun; uji: THR Rp6 juta → kurang potong Rp285.000/orang/tahun, 1721-A1 salah). Sekarang
    penyesuaian pendapatan ± dan pengurangan potongan terlambat/tidak masuk ikut bruto kena pajak; BPJS TIDAK
    berubah (dasar iurannya upah tetap). Return slip baru (deductions, tax, warnings) — total dihitung pemanggil."""
    from routes import rahaza_payroll_rules as rules
    from routes.rahaza_payroll_settings import get_pph21_settings
    emp = emp or {}
    pph_cfg = await get_pph21_settings(db)
    tax = dict(slip.get("tax") or {})
    lines = [dict(d) for d in slip.get("deductions") or []]
    if not pph_cfg.get("enabled"):
        tax.update(taxable_gross=round(max(0.0, float(slip.get("gross_pay") or 0))), pph21={"method": "off"})
        return {**slip, "tax": tax}
    period_to = str(slip.get("period_to") or "")[:10]
    if len(period_to) != 10:   # slip tanpa periode (data rusak) — tidak bisa menentukan bulan pajak
        return slip
    pt = _to_date(period_to)
    taxable = slip_taxable({**slip, "deductions": lines}, pph_cfg)
    hist = await _tax_history(db, slip.get("employee_id"), period_to[:4], run_id)
    figs = [_slip_tax_figures(s) for s in hist]
    jht_jp = sum(float(d.get("amount") or 0) for d in lines if (d.get("type") or "") in ("bpjs_jht", "bpjs_jp"))
    _, end = rules.employment_window(emp)
    res = pph21_line(pph_cfg=pph_cfg, figs=figs, tax_month=tax.get("tax_month") or period_to[:7], taxable=taxable,
                     jht_jp_this=jht_jp, emp=emp, scheme=slip.get("pay_scheme") or "monthly", pt=pt, end=end)
    pos = next((i for i, d in enumerate(lines) if (d.get("type") or "") == "pph21"), None)
    lines = [d for d in lines if (d.get("type") or "") != "pph21"]
    if res["amount"] > 0:
        if pos is None:   # sesudah BPJS, sebelum kasbon (urutan mesin hitung)
            pos = next((i for i, d in enumerate(lines) if (d.get("type") or "") == "kasbon"), len(lines))
        lines.insert(min(pos, len(lines)), {"label": res["label"], "amount": res["amount"], "type": "pph21"})
    tax.update(taxable_gross=round(taxable), pph21=res["detail"],
               includes_manual_addition=round(float(slip.get("manual_addition") or 0)))
    warnings = [w for w in slip.get("warnings") or [] if w.get("type") != "pph21_overpaid"] + res["warnings"]
    return {**slip, "deductions": lines, "tax": tax, "warnings": warnings}


def _bpjs_zero() -> dict:
    return {"kes_emp": 0, "kes_comp": 0, "jht_emp": 0, "jht_comp": 0, "jp_emp": 0, "jp_comp": 0,
            "jkk_comp": 0, "jkm_comp": 0}


async def _employee_period_context(db, emp_id: str, pf: date, pt: date, emp: dict, cal: dict) -> dict:
    """Absensi, cuti, lembur, dan hari kerja satu karyawan untuk satu periode (dipakai slip & koreksi)."""
    from core.workdays import holiday_set, working_days_between
    from routes import rahaza_payroll_rules as rules
    from utils.attendance_policy import attendance_counts
    pfi, pti = pf.isoformat(), pt.isoformat()
    holidays = await holiday_set(db, pf, pt)
    period_wd = working_days_between(pf, pt, cal["off_weekdays"], holidays)
    join, end = rules.employment_window(emp)
    employed_wd = [d for d in period_wd if rules.employed_on(d, join, end)]
    events = await db.rahaza_attendance_events.find(
        {"employee_id": emp_id, "date": _date_range_filter(pfi, pti)}, {"_id": 0}).to_list(1000)
    leaves = await db.rahaza_leave_requests.find(
        {"employee_id": emp_id, "status": "approved", "from_date": {"$lte": pti}, "to_date": {"$gte": pfi}},
        {"_id": 0}).to_list(200)
    lt_ids = list({lv.get("leave_type_id") for lv in leaves if lv.get("leave_type_id")})
    leave_types = {lt["id"]: lt for lt in await db.rahaza_leave_types.find(
        {"id": {"$in": lt_ids}}, {"_id": 0}).to_list(200)} if lt_ids else {}
    try:
        ot_requests = await db.rahaza_overtime_requests.find(
            {"employee_id": emp_id, "status": "approved", "date": _date_range_filter(pfi, pti)},
            {"_id": 0}).to_list(500)
    except Exception as e:  # noqa: BLE001
        ot_requests = []
        log.warning(f"Overtime request aggregation failed for {emp_id}: {e}")
    classified = rules.classify_days(employed_wd, events, leaves, leave_types, counts=attendance_counts)
    return {"holidays": holidays, "period_wd": period_wd, "employed_wd": employed_wd, "join": join, "end": end,
            "events": events, "leaves": leaves, "leave_types": leave_types, "ot_requests": ot_requests,
            "classified": classified}


async def _overtime_clock_hours(db, emp: dict, events: list, dates, off_days: set) -> dict:
    """{tanggal: jam lembur NYATA dari jam absen} — 2026-11-09 (Q9). Hari kerja: jam pulang − jam pulang shift
    (shift tidak diketahui → 8 jam sejak masuk, `core.attendance_rules.shift_end_utc`); hari istirahat/libur:
    jam kerja bersih. Hanya untuk tanggal yang punya pengajuan disetujui / tanda HR (bukan setiap pulang telat)."""
    from core.attendance_rules import _aware, resolve_day_shift, shift_end_utc
    from utils.attendance_policy import attendance_counts
    by = {str(e.get("date") or "")[:10]: e for e in events or [] if attendance_counts(e)}
    out: dict = {}
    for iso in sorted(set(dates or ())):
        r = by.get(iso)
        if not r:
            continue
        cin, cout = _aware(r.get("clock_in")), _aware(r.get("clock_out"))
        if iso in off_days:
            h = r.get("net_hours_worked") if r.get("net_hours_worked") is not None else r.get("hours_worked")
            h = float(h or 0) or ((cout - cin).total_seconds() / 3600 if cin and cout else 0.0)
        else:
            if not cout:
                continue
            shift = await resolve_day_shift(db, emp, iso, r.get("shift_id"))
            end = shift_end_utc(iso, shift, cin)
            if not end:
                continue
            h = max(0.0, (cout - end).total_seconds() / 3600)
        if h > 0:
            out[iso] = round(h, 4)
    return out


async def _overtime_for_context(db, emp: dict, ctx: dict, cal: dict, ot_cfg: dict, *, rule: str) -> list:
    """Lembur per hari satu periode — SATU jalur untuk slip baru dan koreksi slip final (Q9)."""
    from routes import rahaza_payroll_rules as rules
    from utils.attendance_policy import attendance_counts
    clock = {}
    if rule != "legacy":
        wd = {d.isoformat() for d in ctx["period_wd"]}
        want = {str(r.get("date") or "")[:10] for r in ctx["ot_requests"] if r.get("status") == "approved"}
        want |= {str(e.get("date") or "")[:10] for e in ctx["events"] if e.get("overtime_paid") is True}
        off = {iso for iso in want if iso not in wd}
        clock = await _overtime_clock_hours(db, emp, ctx["events"], want, off)
    return rules.overtime_days(ctx["events"], ctx["ot_requests"], ctx["classified"],
                               off_weekdays=cal["off_weekdays"], holidays=ctx["holidays"], cfg=ot_cfg,
                               work_days_per_week=cal["work_days_per_week"], counts=attendance_counts,
                               clock_hours=clock, rule=rule)


async def _attendance_corrections(db, profile: dict, emp: dict, pf: date, run_id: str | None, cal: dict,
                                  ot_cfg: dict) -> tuple[list, list, list]:
    """Koreksi absensi pada periode yang SUDAH final (absensi terkunci) → (baris pendapatan, baris potongan,
    jejak koreksi). Selisih dihitung dari jejak per tanggal (`attendance_snapshot`) slip final vs absensi
    sekarang, dengan tarif harian / upah sejam slip asal. Slip lama tanpa jejak dilewati (konservatif)."""
    from routes import rahaza_payroll_rules as rules
    from utils.attendance_policy import attendance_counts
    emp_id = profile["employee_id"]
    since = (pf - timedelta(days=CORRECTION_LOOKBACK_DAYS)).isoformat()
    prior = await db.rahaza_payslips.find(
        {"employee_id": emp_id, "period_to": {"$lt": pf.isoformat(), "$gte": since},
         "attendance_snapshot": {"$exists": True}}, {"_id": 0}).to_list(20)
    prior = [s for s in prior if s.get("run_id") and s.get("run_id") != run_id]
    if not prior:
        return [], [], []
    finals = {r["id"]: r for r in await db.rahaza_payroll_runs.find(
        {"id": {"$in": list({s["run_id"] for s in prior})}, "status": "finalized"},
        {"_id": 0, "id": 1, "run_number": 1}).to_list(20)}
    earn, ded, trail = [], [], []
    for s in sorted(prior, key=lambda x: str(x.get("period_from"))):
        run = finals.get(s.get("run_id"))
        if not run:
            continue
        # Sudah diklaim slip run lain yang belum dibatalkan (mis. run draft lain) → jangan dobel.
        claims = await db.rahaza_payslips.find(
            {"employee_id": emp_id, "run_id": {"$ne": run_id},
             "corrections": {"$elemMatch": {"source_slip_id": s.get("id")}}}, {"_id": 0, "run_id": 1}).to_list(20)
        if claims and await db.rahaza_payroll_runs.count_documents(
                {"id": {"$in": [c.get("run_id") for c in claims]}, "status": "draft"}):
            continue
        spf, spt = _to_date(str(s["period_from"])[:10]), _to_date(str(s["period_to"])[:10])
        ctx = await _employee_period_context(db, emp_id, spf, spt, emp, cal)
        # Penyatuan absen ↔ payroll (6 Nov 2026): koreksi absen yang disetujui HR untuk tanggal TERKUNCI
        # tidak mengubah absensi (paket absen menyimpannya di `rahaza_attendance_corrections` dengan
        # payroll_adjustment.status='pending'). Terapkan isian koreksinya di atas absensi saat menghitung
        # selisih, lalu tandai 'applied' ketika run ini final (lihat `apply_correction_trail`).
        corr_ids = await _overlay_pending_corrections(db, emp_id, spf, spt, ctx, rules, attendance_counts)
        # Q9 (9 Nov 2026): slip final yang dihitung SEBELUM aturan lembur jam nyata dibandingkan dengan aturan
        # lamanya — perubahan aturan bukan koreksi absen dan tidak boleh memunculkan selisih palsu.
        ot_days = await _overtime_for_context(db, emp, ctx, cal, ot_cfg,
                                              rule=s.get("overtime_rule") or "legacy")
        if s.get("pay_scheme") != "monthly":
            ctx["classified"] = {k: {**v, "weight": 0.0} for k, v in ctx["classified"].items()}
        new_snap = rules.snapshot_of(ctx["classified"], ot_days)
        old_snap = (s["attendance_snapshot_current"] if s.get("attendance_snapshot_current") is not None
                    else s.get("attendance_snapshot")) or {}
        if s.get("pay_scheme") != "monthly":
            old_snap = {k: {**v, "ded": 0.0} for k, v in old_snap.items()}
        delta = rules.snapshot_delta(old_snap, new_snap)
        if not delta:
            continue
        n_period = int((s.get("work_days") or {}).get("period") or len(ctx["period_wd"]) or 0)
        hourly = float(s.get("overtime_base_hourly") or 0)
        amount = 0.0
        for iso, dlt in delta.items():
            if dlt["ded"] and n_period:
                amount -= dlt["ded"] * rules.rate_on(profile, _to_date(iso)) / n_period
            if dlt["ot"] and hourly:
                amount += dlt["ot"] * hourly
        amount = _round(amount)
        if not amount:
            continue
        days = ", ".join(sorted(_to_date(i).strftime("%d/%m") for i in delta))
        label = f"Koreksi absen {run.get('run_number') or ''} ({days})".replace("  ", " ")
        if amount > 0:
            earn.append({"type": "attendance_correction", "label": label, "qty": 1, "unit": "koreksi",
                         "rate": amount, "amount": amount, "source_run_number": run.get("run_number")})
        else:
            ded.append({"type": "absence_correction", "label": label, "amount": -amount,
                        "source_run_number": run.get("run_number")})
        trail.append({"source_slip_id": s.get("id"), "source_run_id": run["id"],
                      "source_run_number": run.get("run_number"), "delta": delta, "amount": amount,
                      "new_snapshot": new_snap, "prev_snapshot": old_snap,
                      "attendance_correction_ids": corr_ids})
    return earn, ded, trail


async def _overlay_pending_corrections(db, emp_id: str, spf: date, spt: date, ctx: dict, rules, counts) -> list:
    """Isian koreksi absen untuk tanggal terkunci ditimpakan ke absensi periode slip asal.

    SEMUA koreksi disetujui (pending maupun sudah dibayar) ikut ditimpakan — itulah absensi yang benar;
    jejak `attendance_snapshot_current` slip asal yang mencegah pembayaran dobel. Yang dikembalikan hanya
    id koreksi yang belum dibayar (ditandai 'applied' saat run final)."""
    pend = await db.rahaza_attendance_corrections.find(
        {"employee_id": emp_id, "status": "approved", "apply_mode": "penyesuaian_payroll",
         "date": {"$gte": spf.isoformat(), "$lte": spt.isoformat()}},
        {"_id": 0}).to_list(200)
    pend.sort(key=lambda c: str(c.get("decided_at") or c.get("created_at") or ""))
    if not pend:
        return []
    from routes.rahaza_attendance_corrections import requested_to_patch
    by_day = {str(e.get("date"))[:10]: e for e in ctx["events"]}
    for c in pend:
        day = str(c.get("date"))[:10]
        patch = requested_to_patch(day, c.get("requested") or {})
        ev = dict(by_day.get(day) or {"employee_id": emp_id, "date": day})
        ev.update(patch)
        # aturan paket absen: jam masuk pada hari alpa/kosong menjadikan statusnya hadir
        if "status" not in patch and patch.get("clock_in") and (ev.get("status") or "") in ("", "alpa", "alfa"):
            ev["status"] = "hadir"
        by_day[day] = ev
    ctx["events"] = list(by_day.values())
    ctx["classified"] = rules.classify_days(ctx["employed_wd"], ctx["events"], ctx["leaves"], ctx["leave_types"],
                                            counts=counts)
    return [c["id"] for c in pend if c.get("id") and ((c.get("payroll_adjustment") or {}).get("status") or "pending") == "pending"]


async def _compute_payslip_for_employee(db, profile: dict, period_from: str,
                                        period_to: str, emp: dict, *, run_id: str | None = None) -> dict:
    """Hitung slip payroll untuk 1 pegawai. SATU-SATUNYA mesin hitung.

    Komponen (mengikuti sheet "Data THP" milik user):
      PENDAPATAN  gaji pokok (prorata) / borongan pcs / jam · lembur · tunjangan · koreksi absen
      POTONGAN    keterlambatan · tidak masuk (alpa/cuti tak dibayar) · BPJS · PPh21 · kasbon/pinjaman
    `run_id` = run yang sedang dibuat/dihitung ulang (dikecualikan dari riwayat pajak & koreksi).
    """
    from core.workdays import get_work_calendar
    from routes import rahaza_payroll_rules as rules
    from routes.rahaza_payroll_settings import (get_attendance_bonus_settings, get_bpjs_settings,
                                                get_overtime_settings, get_pph21_settings)
    from routes.rahaza_payroll_tax import compute_bpjs, resolve_bpjs_programs, _pct
    from utils.attendance_policy import attendance_counts

    scheme = profile["pay_scheme"]
    emp_id = profile["employee_id"]
    pf, pt = _to_date(period_from[:10]), _to_date(period_to[:10])
    base_rate = rules.rate_on(profile, pt)            # tarif berlaku di akhir periode (label & cadangan)
    ot_rate = rules.rate_on(profile, pt, "overtime_rate")
    warnings: list = []

    earnings: list = []
    source_refs: dict = {"wip_event_count": 0, "attendance_event_count": 0, "process_breakdown": {}}

    # ─── KALENDER & ABSENSI ───────────────────────────────────────────────────
    cal = await get_work_calendar(db)
    ctx = await _employee_period_context(db, emp_id, pf, pt, emp, cal)
    period_wd, employed_wd, classified = ctx["period_wd"], ctx["employed_wd"], ctx["classified"]
    n_period, n_emp = len(period_wd), len(employed_wd)
    fixed_scheme = scheme in ("monthly", "weekly")
    emp_factor = (n_emp / n_period) if (fixed_scheme and n_period) else 1.0
    source_refs["attendance_event_count"] = len(ctx["events"])
    # Tahap 1 (keputusan owner): selfie DITOLAK HR bukan kehadiran — tidak dihitung hadir, jam kerja,
    # lembur, maupun terlambat. Selfie yang masih menunggu review tetap dihitung (SSOT attendance_policy).
    att_rows = [r for r in ctx["events"] if attendance_counts(r)]
    if len(att_rows) != len(ctx["events"]):
        source_refs["attendance_rejected_count"] = len(ctx["events"]) - len(att_rows)
    source_refs["overtime_request_count"] = len(ctx["ot_requests"])
    day_sum = rules.summarize_days(classified, until=today_wib())

    total_hours = sum(float(r.get("hours_worked") or 0) for r in att_rows)
    # FASE 15: jam BERSIH (sudah dikurangi istirahat & izin keluar).
    total_net_hours = sum(
        float(r.get("net_hours_worked") if r.get("net_hours_worked") is not None
              else (r.get("hours_worked") or 0))
        for r in att_rows
    )
    days_hadir = sum(1 for r in att_rows if rules.norm_status(r.get("status")) == "hadir")
    # 2026-11-09 (H5): terlambat hanya dari hari hadir / setengah hari cuti di HARI KERJA (catatan cuti/izin sehari
    # penuh, tugas luar, dan lembur hari Minggu/libur tanpa jadwal terbit diabaikan — termasuk menit lama tersimpan).
    _wd_iso = {d.isoformat() for d in period_wd}
    _off_days = {str(r.get("date") or "")[:10] for r in att_rows} - _wd_iso
    late_rows = [r for r in att_rows if rules.timing_counts(r, off_days=_off_days)]
    total_late_minutes = sum(int(r.get("late_minutes") or 0) for r in late_rows)
    days_late = sum(1 for r in late_rows if int(r.get("late_minutes") or 0) > 0)
    # Q3: pulang cepat DICATAT (informasi slip & rekap) — tidak memotong gaji/bonus.
    total_early_minutes = sum(int(r.get("early_leave_minutes") or 0) for r in late_rows)
    days_early = sum(1 for r in late_rows if int(r.get("early_leave_minutes") or 0) > 0)
    total_break_minutes = sum(int(r.get("break_minutes") or 0) for r in att_rows)
    total_permit_minutes = sum(int(r.get("permit_minutes") or 0) for r in att_rows)
    source_refs.update({
        "late_minutes": total_late_minutes, "days_late": days_late,
        "early_leave_minutes": total_early_minutes, "days_early_leave": days_early,
        "break_minutes": total_break_minutes, "permit_minutes": total_permit_minutes,
    })
    if fixed_scheme and n_period == 0:
        warnings.append({"type": "no_work_days", "message": "Periode ini tidak punya hari kerja di kalender kerja — "
                                                           "gaji tetap dibayar penuh tanpa prorata."})
    if fixed_scheme and n_period and n_emp == 0:
        warnings.append({"type": "not_employed", "message": "Tanggal masuk/keluar karyawan berada di luar periode ini — "
                                                           "tidak ada hari kerja yang dibayar."})
    if fixed_scheme and day_sum["tanpa_catatan"]:
        warnings.append({"type": "attendance_missing",
                         "message": f"{day_sum['tanpa_catatan']} hari kerja tanpa catatan absen — tidak dipotong "
                                    "otomatis dan tidak menghanguskan bonus kehadiran. Periksa absensinya sebelum "
                                    "finalisasi."})
    # Q1 (9 Nov 2026): hari kerja tanpa catatan dianggap hadir untuk bonus kehadiran (termasuk sisa periode yang
    # belum berjalan saat run dibuat) — sama dengan aturan gaji pokok.
    presumed_days = sum(1 for r in classified.values() if r.get("kind") == "tanpa_catatan")

    # ─── PENDAPATAN per skema ─────────────────────────────────────────────────
    def _segments(days):
        segs: list = []
        for d in days:
            r = rules.rate_on(profile, d)
            if segs and segs[-1]["rate"] == r:
                segs[-1]["days"].append(d)
            else:
                segs.append({"rate": r, "days": [d]})
        return segs

    if scheme == "pcs":
        # Dua penulis event WIP dengan nama field berbeda (temuan FASE 15) — keduanya diterima.
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
        # Tarif per tanggal: kenaikan tarif di tengah periode berlaku mulai tanggal efektifnya.
        amount = 0.0
        for r in att_rows:
            h = float(r.get("net_hours_worked") if r.get("net_hours_worked") is not None else (r.get("hours_worked") or 0))
            dd = rules._d(r.get("date")) or pt
            amount += h * rules.rate_on(profile, dd)
        earnings.append({
            "type": "hourly", "label": "Borongan jam",
            "qty": round(total_net_hours, 2), "unit": "jam",
            "rate": base_rate, "amount": round(amount),
        })

    elif scheme == "weekly":
        try:
            weeks = max(1, round(((pt - pf).days + 1) / 7))
        except Exception:  # noqa: BLE001
            weeks = 1
        if n_period:
            amount = weeks * sum(rules.rate_on(profile, d) for d in employed_wd) / n_period
        else:
            amount = weeks * base_rate
        label = "Gaji mingguan" + (f" — {n_emp}/{n_period} hari kerja" if n_period and n_emp != n_period else "")
        earnings.append({"type": "weekly", "label": label, "qty": weeks, "unit": "minggu",
                         "rate": base_rate, "amount": round(amount),
                         "work_days": n_emp, "work_days_period": n_period})

    elif scheme == "monthly":
        segs = _segments(employed_wd) if n_period else []
        if not n_period:
            earnings.append({"type": "monthly", "label": "Gaji pokok (bulanan)", "qty": 1,
                             "unit": "bulan", "rate": base_rate, "amount": round(base_rate)})
        elif len(segs) == 1 and n_emp == n_period:
            earnings.append({"type": "monthly", "label": "Gaji pokok (bulanan)", "qty": 1,
                             "unit": "bulan", "rate": segs[0]["rate"], "amount": round(segs[0]["rate"])})
        else:
            # Prorata: tarif × hari kerja dibayar ÷ hari kerja periode, satu baris per versi tarif.
            for sg in segs:
                n = len(sg["days"])
                lbl = f"Gaji pokok (bulanan) — {n}/{n_period} hari kerja"
                if len(segs) > 1:
                    lbl += f" mulai {sg['days'][0].strftime('%d/%m')}"
                earnings.append({"type": "monthly", "label": lbl, "qty": round(n / n_period, 4), "unit": "bulan",
                                 "rate": sg["rate"], "amount": round(sg["rate"] * n / n_period),
                                 "work_days": n, "work_days_period": n_period, "prorated": True})

    # ─── KOREKSI ABSEN periode final sebelumnya ───────────────────────────────
    ot_cfg = await get_overtime_settings(db)
    corr_earn, corr_ded, corr_trail = await _attendance_corrections(db, profile, emp, pf, run_id, cal, ot_cfg)
    base_earnings_total = sum(e["amount"] for e in earnings)
    earnings.extend(corr_earn)
    earnings_total = sum(e["amount"] for e in earnings)
    applicable_allowances = await _get_applicable_allowances(db, emp)

    # ─── LEMBUR per hari (Tahap 2) ────────────────────────────────────────────
    ot_days = await _overtime_for_context(db, emp, ctx, cal, ot_cfg, rule=rules.OVERTIME_RULE)
    paid_factor = round(sum(o["factor"] for o in ot_days), 4)
    no_att = [o["date"] for o in ot_days if o["basis"] == "pengajuan tanpa absen"]
    if no_att:
        warnings.append({"type": "overtime_no_attendance",
                         "message": f"Lembur disetujui tanpa catatan absen ({', '.join(_to_date(d).strftime('%d/%m') for d in no_att)})"
                                    " — tidak dibayar. Lengkapi absen pulang / jam lembur di absensi bila lemburnya ada."})
    for msg in rules.overtime_limit_warnings(ot_days):
        warnings.append({"type": "overtime_limit", "message": f"Lembur melebihi batas PP 35/2021 — {msg}."})
    paid_hours = round(sum(o["paid_hours"] for o in ot_days), 2)
    unpaid_hours = round(sum(o["hours"] - o["paid_hours"] for o in ot_days if o["basis"] == "tanpa pengajuan"), 2)
    fixed_allow_full = sum(float(al.get("amount") or 0) for al in applicable_allowances
                           if al.get("is_fixed_wage") and (al.get("calc_type") or "fixed") == "fixed")
    upah_tetap_contract = base_rate + fixed_allow_full
    overtime_amount = 0
    overtime_basis = "none"
    overtime_base_hourly = 0.0
    overtime_warning = None
    if paid_factor > 0:
        first_mult = float(ot_cfg.get("first_hour_multiplier") or 1.5)
        if ot_rate > 0:
            # Tarif Profil Gaji = Rp per jam lembur pertama hari kerja → upah sejam = tarif ÷ pengali jam ke-1.
            overtime_base_hourly, overtime_basis = ot_rate / first_mult, "profile"
        elif scheme == "hourly" and base_rate > 0:
            overtime_base_hourly, overtime_basis = base_rate, "upah_sejam"
        elif ot_cfg.get("basis") == "upah_tetap_div_173" and scheme == "monthly" and upah_tetap_contract > 0:
            overtime_base_hourly = upah_tetap_contract / float(ot_cfg.get("divisor") or 173)
            overtime_basis = "upah_tetap_div_173"
        else:
            overtime_warning = (f"Ada {paid_hours:g} jam lembur disetujui tetapi tarif lembur Profil Gaji = 0 dan aturan "
                                "cadangan tidak berlaku (bukan skema bulanan / basis 'manual') — lembur TIDAK dibayar. "
                                "Isi tarif lembur di Profil Gaji atau Pengaturan gaji.")
        overtime_amount = round(overtime_base_hourly * paid_factor)
        source_refs["overtime_factor"] = paid_factor
    if overtime_warning:
        warnings.append({"type": "overtime_rate_zero", "message": overtime_warning})
    if unpaid_hours > 0:
        source_refs["overtime_unapproved_hours"] = unpaid_hours
        warnings.append({"type": "overtime_unapproved",
                         "message": f"{unpaid_hours:g} jam lembur tanpa pengajuan disetujui — tidak dibayar sampai HR "
                                    "menandainya dibayar di absensi."})

    # ─── TUNJANGAN ────────────────────────────────────────────────────────────
    bonus_cfg = await get_attendance_bonus_settings(db)
    allowance_items: list = []
    allowance_total = 0.0
    fixed_wage_allowance = 0.0   # dasar iuran BPJS skema non-bulanan (upah tetap periode ini)
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
            amount = amt_cfg * emp_factor   # prorata masa kerja (skema bulanan/mingguan)
        else:
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
                    else round(total_net_hours, 2) if calc_type == "per_hour_worked"
                    else round(emp_factor, 4) if calc_type == "fixed" and emp_factor != 1 else 1),
            "amount": round(amount),
            "is_fixed_wage": bool(al.get("is_fixed_wage")),
        }
        if warning:
            item["warning"] = warning
        if rules.is_attendance_bonus(al, bonus_cfg):
            reasons = rules.bonus_forfeit_reasons(bonus_cfg, day_sum, days_present=days_hadir,
                                                  days_late=days_late, late_minutes=total_late_minutes,
                                                  presumed_days=presumed_days)
            if reasons:
                item.update(amount=0, forfeited=True, forfeit_reasons=reasons,
                            label=f"{item['label']} — hangus: {', '.join(reasons)}")
        allowance_items.append(item)
        allowance_total += item["amount"]
        if item["is_fixed_wage"]:
            fixed_wage_allowance += item["amount"]

    gross = earnings_total + overtime_amount + allowance_total

    # ─── POTONGAN ─────────────────────────────────────────────────────────────
    deductions: list = []
    deductions_total = 0.0

    # (1) KETERLAMBATAN — aturan di `rahaza_payroll_settings`; tanpa aturan → TIDAK memotong.
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
                for row in late_rows:
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

    # (2) TIDAK MASUK — satu aturan (menggantikan LWOP terpisah): alpa + izin/sakit/cuti tidak dibayar /
    #     tanpa pengajuan disetujui. Gaji pokok ÷ hari kerja periode × hari potongan (setengah hari 0,5).
    if scheme == "monthly" and n_period and day_sum["potong_hari"] > 0:
        ded_days = [(iso, r) for iso, r in sorted(classified.items()) if r["weight"] > 0]
        amount = _round(sum(r["weight"] * rules.rate_on(profile, _to_date(iso)) / n_period for iso, r in ded_days))
        parts = []
        if day_sum["alpa"]:
            parts.append(f"alpa {day_sum['alpa']:g}")
        if day_sum["tidak_dibayar"]:
            parts.append(f"izin/sakit/cuti tidak dibayar {day_sum['tidak_dibayar']:g}")
        if amount > 0:
            deductions.append({
                "type": "absence",
                "label": f"Potongan tidak masuk ({day_sum['potong_hari']:g} hari: {', '.join(parts)})",
                "days": day_sum["potong_hari"], "alpa_days": day_sum["alpa"],
                "unpaid_leave_days": day_sum["tidak_dibayar"], "divisor": n_period,
                "daily_rate": round(base_rate / n_period), "dates": [iso for iso, _ in ded_days],
                "amount": amount,
            })
            deductions_total += amount
            source_refs["absence_days"] = day_sum["potong_hari"]
            source_refs["absence_amount"] = amount
    for c in corr_ded:
        deductions.append(c)
        deductions_total += c["amount"]

    # (3) BPJS + PPh21 — SEMUA skema (Tahap 2), dihitung kumulatif per BULAN PAJAK (bulan period_to):
    #     iuran/pajak bulan itu dikurangi yang sudah dipotong slip run lain di bulan yang sama
    #     (run mingguan tidak memotong iuran bulanan 4×). Dihitung SEBELUM kasbon.
    #     Dasar iuran BPJS skema bulanan = UPAH TETAP kontrak (gaji pokok + tunjangan tetap, tidak dipotong
    #     absen/prorata); skema lain = upah periode (borongan/jam/mingguan + tunjangan tetap) kumulatif.
    bpjs_employer = {"kes": 0, "jht": 0, "jp": 0, "jkk": 0, "jkm": 0, "kes_total": 0, "tk_total": 0, "total": 0}
    bpjs_programs = {"kes": False, "jht": False, "jp": False, "jkk_jkm": False}
    tax_info: dict = {"tax_month": period_to[:7]}
    try:
        bpjs_programs = resolve_bpjs_programs(emp)
        apply_bpjs = any(bpjs_programs.values())
        from routes.rahaza_payroll_tax import apply_jp_ceiling_schedule
        bpjs_cfg = apply_jp_ceiling_schedule(await get_bpjs_settings(db), pt)   # M4: plafon JP per tanggal
        pph_cfg = await get_pph21_settings(db)
        hist = await _tax_history(db, emp_id, period_to[:4], run_id)
        figs = [_slip_tax_figures(s) for s in hist]
        month_prior = [f for f in figs if f["tax_month"] == tax_info["tax_month"]]
        pm = {k: sum(f[k] for f in month_prior) for k in ("taxable", "bpjs_base", "pph21", "kes", "jht", "jp")}
        pm_er = {k: sum(f["er"][k] for f in month_prior) for k in ("kes", "jht", "jp", "jkk", "jkm")}

        if scheme == "monthly":
            last_day = employed_wd[-1] if employed_wd else pt
            this_base = rules.rate_on(profile, last_day) + fixed_allow_full
            month_base = this_base
        else:
            this_base = base_earnings_total + fixed_wage_allowance
            month_base = pm["bpjs_base"] + this_base
        tax_info.update(bpjs_base=round(this_base), bpjs_month_base=round(month_base))
        mb = compute_bpjs(month_base, programs=bpjs_programs, cfg=bpjs_cfg) if apply_bpjs else _bpjs_zero()
        cur = {"kes_emp": max(0, mb["kes_emp"] - _round(pm["kes"])),
               "jht_emp": max(0, mb["jht_emp"] - _round(pm["jht"])),
               "jp_emp": max(0, mb["jp_emp"] - _round(pm["jp"])),
               "kes_comp": max(0, mb["kes_comp"] - _round(pm_er["kes"])),
               "jht_comp": max(0, mb["jht_comp"] - _round(pm_er["jht"])),
               "jp_comp": max(0, mb["jp_comp"] - _round(pm_er["jp"])),
               "jkk_comp": max(0, mb["jkk_comp"] - _round(pm_er["jkk"])),
               "jkm_comp": max(0, mb["jkm_comp"] - _round(pm_er["jkm"]))}
        rates = bpjs_cfg.get("rates") or {}
        for key, typ, lbl, rk in (("kes_emp", "bpjs_kesehatan", "BPJS Kesehatan", "kes_emp"),
                                  ("jht_emp", "bpjs_jht", "BPJS Ketenagakerjaan JHT", "jht_emp"),
                                  ("jp_emp", "bpjs_jp", "BPJS Ketenagakerjaan JP", "jp_emp")):
            if cur[key] > 0:
                deductions.append({"label": f"{lbl} ({_pct(rates.get(rk, 0))})", "amount": cur[key], "type": typ})
                deductions_total += cur[key]
        source_refs["bpjs_base_upah_tetap"] = round(this_base)
        if apply_bpjs:
            kes_t = cur["kes_comp"]
            tk_t = cur["jht_comp"] + cur["jp_comp"] + cur["jkk_comp"] + cur["jkm_comp"]
            bpjs_employer = {"kes": cur["kes_comp"], "jht": cur["jht_comp"], "jp": cur["jp_comp"],
                             "jkk": cur["jkk_comp"], "jkm": cur["jkm_comp"], "kes_total": kes_t, "tk_total": tk_t,
                             "total": kes_t + tk_t, "jkk_risk_tier": bpjs_cfg.get("jkk_risk_tier")}

        # PPh21 — bruto = upah (bruto − potongan terlambat/tidak masuk) + premi JKK/JKM/Kes perusahaan.
        if pph_cfg.get("enabled"):
            wage_cut = sum(float(d["amount"]) for d in deductions if d.get("type") in SYSTEM_WAGE_DEDUCTIONS)
            premiums = (cur["jkk_comp"] + cur["jkm_comp"] + cur["kes_comp"]) if pph_cfg.get("employer_premiums_taxable") else 0
            taxable = max(0.0, gross - wage_cut) + premiums
            # 2026-11-09 (H3): rumus PPh21 satu tempat (`pph21_line`) — dipakai juga penyesuaian slip (Adj).
            res = pph21_line(pph_cfg=pph_cfg, figs=figs, tax_month=tax_info["tax_month"], taxable=taxable,
                             jht_jp_this=cur["jht_emp"] + cur["jp_emp"], emp=emp, scheme=scheme, pt=pt,
                             end=ctx["end"])
            warnings.extend(res["warnings"])
            pph = res["amount"]
            if pph > 0:
                deductions.append({"label": res["label"], "amount": pph, "type": "pph21"})
                deductions_total += pph
            tax_info.update(taxable_gross=round(taxable), pph21=res["detail"])
        else:
            tax_info.update(taxable_gross=round(max(0.0, gross)), pph21={"method": "off"})
    except Exception as e:  # noqa: BLE001
        log.warning(f"PPh21/BPJS calculation failed for {emp_id}: {e}")
        warnings.append({"type": "tax_error", "message": f"BPJS/PPh21 gagal dihitung: {e}"})

    # (4) KASBON / PINJAMAN — dibatasi sisa gaji yang tersedia (THP tidak boleh negatif).
    #     Iter 120: dulu memotong SELURUH saldo kasbon walau gaji periode lebih kecil ⇒ net_pay minus.
    try:
        period_ym = rules.payroll_month(period_from, period_to)   # M2: bulan gaji = bulan akhir periode
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
    if net_pay < 0:
        warnings.append({"type": "negative_net",
                         "message": f"Gaji bersih minus Rp {-net_pay:,.0f} — potongan melebihi bruto. Run tidak bisa "
                                    "difinalisasi sebelum diperbaiki.".replace(",", ".")})

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
        "overtime_hours": paid_hours,
        "overtime_rate": round(overtime_base_hourly * float(ot_cfg.get("first_hour_multiplier") or 1.5), 2)
        if overtime_basis == "profile" else round(overtime_base_hourly, 2),
        "overtime_amount": overtime_amount,
        # 2026-11-02 (K24) + 2026-11-06 (Tahap 2): asal tarif lembur + rincian per hari
        "overtime_basis": overtime_basis,
        "overtime_base_hourly": round(overtime_base_hourly, 2),
        "overtime_entries": ot_days,
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
        "early_leave_minutes": total_early_minutes,     # Q3: informasi, tidak memotong
        "days_early_leave": days_early,
        "overtime_rule": rules.OVERTIME_RULE,
        "payroll_month": rules.payroll_month(period_from, period_to),
        "break_minutes": total_break_minutes,
        "permit_minutes": total_permit_minutes,
        # 2026-11-06 (Tahap 2): dasar hitung yang terlihat di slip + jejak untuk koreksi sesudah kunci
        "work_days": {"period": n_period, "employed": n_emp, "per_week": cal["work_days_per_week"],
                      "join_date": ctx["join"].isoformat() if ctx["join"] else None,
                      "end_date": ctx["end"].isoformat() if ctx["end"] else None},
        "attendance_summary": day_sum,
        "attendance_snapshot": rules.snapshot_of(classified if scheme == "monthly"
                                                 else {k: {**v, "weight": 0.0} for k, v in classified.items()},
                                                 ot_days),
        "corrections": corr_trail,
        "tax": tax_info,
        "warnings": warnings,
        "gross_pay": gross,
        "deductions": deductions,
        "deductions_total": deductions_total,
        "net_pay": net_pay,
        "source_refs": source_refs,
        "notes": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RUN: PERINGATAN, HITUNG ULANG, PEMISAHAN TUGAS, KUNCI (Tahap 2, 2026-11-06)
# ═══════════════════════════════════════════════════════════════════════════════

def run_warnings(payslips: list) -> list:
    """Peringatan run dari slip (ditampilkan di layar Proses Gaji)."""
    return [{"type": w.get("type"), "employee_id": s.get("employee_id"), "employee_name": s.get("employee_name") or "",
             "message": w.get("message")}
            for s in payslips for w in (s.get("warnings") or [])]


def negative_net_slips(payslips: list) -> list:
    return [{"employee_id": s.get("employee_id"), "employee_name": s.get("employee_name") or s.get("employee_code") or "",
             "net_pay": float(s.get("net_pay") or 0)}
            for s in payslips if float(s.get("net_pay") or 0) < 0]


def _adj_key(d: dict) -> tuple:
    return ((d.get("type") or "").lower(), d.get("kasbon_id") or "", "" if d.get("kasbon_id") else (d.get("label") or ""))


def carry_manual_adjustments(old: dict, new: dict) -> dict:
    """Hitung ulang run draft: penyesuaian manual HR (pendapatan ±, potongan tambahan, pengurangan baris
    potongan sistem) DIPERTAHANKAN di atas hasil hitung baru."""
    addition = round(float(old.get("manual_addition") or 0))
    deduction = round(float(old.get("manual_deduction") or 0))
    reduced = {_adj_key(d): float(d.get("amount") or 0) for d in (old.get("deductions") or []) if d.get("adjusted")}
    lines = []
    for d in new.get("deductions") or []:
        d = dict(d)
        k = _adj_key(d)
        if k in reduced and not str(d.get("type") or "").lower().startswith(("bpjs", "pph21")):
            orig = float(d.get("amount") or 0)
            d["original_amount"] = orig
            d["amount"] = round(min(reduced[k], orig))
            d["adjusted"] = abs(d["amount"] - orig) > 0.01
        lines.append(d)
    gross_base = float(new.get("gross_pay") or 0)
    out = {**new, "deductions": lines, "id": old.get("id") or new.get("id")}
    for k in ("run_id", "run_number", "created_at", "adjustments_log", "adjustment_notes"):
        if k in old:
            out[k] = old[k]
    if addition or deduction or any(d.get("adjusted") for d in lines):
        out.update(manual_addition=addition, manual_deduction=deduction, gross_before_adjustment=gross_base,
                   gross_pay=round(gross_base + addition))
    ded_total, _net = _payslip_totals(out, deductions=lines, manual_deduction=deduction)
    out["deductions_total"] = ded_total
    out["net_pay"] = float(out["gross_pay"]) - ded_total
    return out


SOD_OVERRIDE_ROLES = ("superadmin", "admin", "owner")


def check_segregation(run: dict, user: dict, action: str, reason: str | None) -> dict | None:
    """K25 (Tahap 2): finalisasi & pembayaran gaji oleh orang LAIN dari pembuat run. Admin/owner boleh
    mengecualikan dengan alasan (dicatat). Return catatan pengecualian atau None; melempar 403 bila ditolak."""
    creator = run.get("created_by")
    if not creator or creator != user.get("id"):
        return None
    role = (user.get("role") or "").lower()
    what = "memfinalisasi" if action == "finalize" else "membayar"
    if role in SOD_OVERRIDE_ROLES and (reason or "").strip():
        return {"action": action, "by": user.get("id"), "by_name": user.get("name", ""), "role": role,
                "reason": reason.strip(), "at": _now()}
    if role in SOD_OVERRIDE_ROLES:
        raise HTTPException(403, (f"Pemisahan tugas: Anda membuat run ini, jadi tidak boleh {what}nya sendiri. "
                                  "Sebagai admin/owner Anda boleh mengecualikan dengan mengisi alasan."))
    raise HTTPException(403, (f"Pemisahan tugas: run ini dibuat oleh Anda — {what} harus dilakukan pengguna lain "
                              "(HR/manajer lain, atau admin/owner dengan alasan)."))


async def apply_correction_trail(db, payslips: list, *, revert: bool = False) -> int:
    """Run final: tandai koreksi absen yang dibawa slipnya sebagai sudah dibayar (jejak slip asal diperbarui).
    `revert=True` (run dibatalkan): kembalikan jejak supaya koreksi dibawa lagi oleh run berikutnya."""
    n = 0
    for s in payslips or []:
        for c in s.get("corrections") or []:
            snap = c.get("prev_snapshot") if revert else c.get("new_snapshot")
            if c.get("source_slip_id") and snap is not None:
                await db.rahaza_payslips.update_one({"id": c["source_slip_id"]},
                                                    {"$set": {"attendance_snapshot_current": snap}})
                n += 1
            # koreksi absen (paket absen) yang ikut dibayar run ini → applied; run dibatalkan → pending lagi
            for cid in c.get("attendance_correction_ids") or []:
                adj = ({"status": "pending", "run_id": None, "applied_at": None} if revert else
                       {"status": "applied", "run_id": s.get("run_id"), "applied_at": datetime.now(timezone.utc)})
                await db.rahaza_attendance_corrections.update_one({"id": cid}, {"$set": {"payroll_adjustment": adj}})
    return n


# Kunci absensi — paket absen memanggil `is_attendance_locked(db, employee_id, date)` dari modul ini.
from routes.rahaza_payroll_rules import attendance_lock, is_attendance_locked  # noqa: E402,F401


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
             "bank_name": r.get("bank_name") or "", "account_number": r.get("account_number") or "",
             "entity": r.get("entity") or "DA"}   # Tahap 8: pemilik rekening (layar menyaring per CV)
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
