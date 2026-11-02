"""
CV. Dewi Aditya / PT Rahaza — Tax & BPJS Calculator (Phase 8.8)

Indonesia-compliant calculation helpers for payroll:
  - PPh21 (Pajak Penghasilan Pasal 21) — progressive bracket based on PTKP
  - BPJS Kesehatan (health insurance) — 1% employee / 4% employer, ceiling 12M
  - BPJS Ketenagakerjaan (JHT/JP/JKK/JKM)

These are pure functions — no DB calls. Called from rahaza_payroll.py during
payroll run generation.

Reference (year 2024/2025 tarif):
  PTKP annual:
    TK/0 = 54,000,000   TK/1 = 58,500,000   TK/2 = 63,000,000   TK/3 = 67,500,000
    K/0  = 58,500,000   K/1  = 63,000,000   K/2  = 67,500,000   K/3  = 72,000,000

  PPh21 progressive (UU HPP):
    0 - 60,000,000       → 5%
    60 - 250,000,000     → 15%
    250 - 500,000,000    → 25%
    500 - 5,000,000,000  → 30%
    > 5,000,000,000      → 35%

  Biaya Jabatan: 5% × gross (max 6,000,000/year or 500,000/month)

  BPJS Kesehatan:
    Total 5% × gross (ceiling 12,000,000)
    Employee = 1%, Employer = 4%

  BPJS Ketenagakerjaan:
    JHT (Hari Tua): 5.7% = 2% employee + 3.7% employer (no ceiling)
    JP  (Pensiun):  3%   = 1% employee + 2%   employer (ceiling 10,042,300)
    JKK (Kecelakaan Kerja): 0.24% - 1.74% employer only (risk tier; bawaan very_low = 0.24%)
    JKM (Kematian): 0.30% employer only

2026-11-02 (keputusan owner K22/K23): tarif, plafon, dan kelas risiko JKK di atas hanya NILAI BAWAAN.
Nilai yang berlaku dibaca dari `rahaza_payroll_settings` (key "bpjs", lihat rahaza_payroll_settings.py)
dan dikirim ke fungsi di sini lewat parameter `cfg`. Kepesertaan per program per karyawan
(`rahaza_employees.bpjs_programs`) dikirim lewat parameter `programs` — lihat resolve_bpjs_programs().
"""
from typing import Dict, Optional


# ─── Constants ───────────────────────────────────────────────────────────────
PTKP_ANNUAL = {
    "TK/0": 54_000_000, "TK/1": 58_500_000, "TK/2": 63_000_000, "TK/3": 67_500_000,
    "K/0":  58_500_000, "K/1":  63_000_000, "K/2":  67_500_000, "K/3":  72_000_000,
}

PPH21_BRACKETS = [
    (60_000_000,      0.05),
    (250_000_000,     0.15),
    (500_000_000,     0.25),
    (5_000_000_000,   0.30),
    (float("inf"),    0.35),
]

BIAYA_JABATAN_RATE = 0.05
BIAYA_JABATAN_MAX_ANNUAL = 6_000_000

# BPJS
BPJS_KES_CEILING = 12_000_000
BPJS_KES_EMP_RATE = 0.01
BPJS_KES_COMP_RATE = 0.04

BPJS_JHT_EMP_RATE = 0.02
BPJS_JHT_COMP_RATE = 0.037

BPJS_JP_CEILING = 10_042_300
BPJS_JP_EMP_RATE = 0.01
BPJS_JP_COMP_RATE = 0.02

BPJS_JKK_RATES = {  # company pays, risk tier
    "very_low":  0.0024,
    "low":       0.0054,
    "medium":    0.0089,
    "high":      0.0127,
    "very_high": 0.0174,
}
BPJS_JKM_COMP_RATE = 0.003

# 2026-11-02 (K22): satu bentuk konfigurasi BPJS. Nilai bawaan = konstanta di atas (tidak diduplikasi
# angka di tempat lain); rahaza_payroll_settings.DEFAULT_BPJS dibangun dari fungsi ini.
BPJS_PROGRAM_KEYS = ("kes", "jht", "jp", "jkk_jkm")


def default_bpjs_config() -> Dict:
    return {
        "rates": {
            "kes_emp": BPJS_KES_EMP_RATE, "kes_comp": BPJS_KES_COMP_RATE,
            "jht_emp": BPJS_JHT_EMP_RATE, "jht_comp": BPJS_JHT_COMP_RATE,
            "jp_emp": BPJS_JP_EMP_RATE, "jp_comp": BPJS_JP_COMP_RATE,
            "jkm_comp": BPJS_JKM_COMP_RATE,
        },
        "ceilings": {"kes": BPJS_KES_CEILING, "jp": BPJS_JP_CEILING},
        "jkk_rates": dict(BPJS_JKK_RATES),
        "jkk_risk_tier": "very_low",
    }


def merge_bpjs_config(stored: Optional[Dict]) -> Dict:
    """Gabungkan dokumen setelan tersimpan dengan nilai bawaan (kunci yang hilang = bawaan)."""
    cfg = default_bpjs_config()
    stored = stored or {}
    for grp in ("rates", "ceilings", "jkk_rates"):
        for k, v in (stored.get(grp) or {}).items():
            if k in cfg[grp] and v is not None:
                try:
                    cfg[grp][k] = float(v)
                except (TypeError, ValueError):
                    pass
    tier = stored.get("jkk_risk_tier")
    if tier in cfg["jkk_rates"]:
        cfg["jkk_risk_tier"] = tier
    return cfg


def resolve_bpjs_programs(emp: Optional[Dict]) -> Dict[str, bool]:
    """Kepesertaan BPJS per program untuk satu karyawan (K23, 2026-11-02).

    - Bila `bpjs_programs` sudah diisi HR (dict) → itulah yang berlaku (kunci yang hilang = tidak ikut).
    - Data lama tanpa centang: punya nomor BPJS Kesehatan → Kes; punya nomor BPJS Ketenagakerjaan →
      JHT, JP, JKK-JKM. TIDAK ADA lagi aturan "nomor apa pun → Kes dipotong" (dulu pemegang nomor TK
      saja ikut dipotong Kes 1%, temuan No.40)."""
    emp = emp or {}
    explicit = emp.get("bpjs_programs")
    if isinstance(explicit, dict):
        return {k: bool(explicit.get(k)) for k in BPJS_PROGRAM_KEYS}
    has_kes = bool(str(emp.get("bpjs_kesehatan_number") or "").strip())
    has_tk = bool(str(emp.get("bpjs_ketenagakerjaan_number") or "").strip())
    return {"kes": has_kes, "jht": has_tk, "jp": has_tk, "jkk_jkm": has_tk}


def normalize_bpjs_programs(value) -> Optional[Dict[str, bool]]:
    """Bersihkan isian form karyawan → {kes, jht, jp, jkk_jkm} bool. None bila tidak dikirim."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("bpjs_programs harus berupa objek {kes, jht, jp, jkk_jkm}.")
    return {k: bool(value.get(k)) for k in BPJS_PROGRAM_KEYS}


def overtime_tier_factor(hours: float, first_mult: float = 1.5, next_mult: float = 2.0) -> float:
    """Faktor pengali lembur hari kerja (K24): jam ke-1 × first_mult, jam berikutnya × next_mult.
    Contoh 3 jam: 1×1,5 + 2×2 = 5,5."""
    h = max(0.0, float(hours or 0))
    return min(h, 1.0) * float(first_mult) + max(h - 1.0, 0.0) * float(next_mult)


# ─── PPh21 ───────────────────────────────────────────────────────────────────
def compute_biaya_jabatan_monthly(monthly_gross: float) -> float:
    """5% of gross, capped at 500k/month."""
    return min(monthly_gross * BIAYA_JABATAN_RATE, BIAYA_JABATAN_MAX_ANNUAL / 12)


def compute_pph21_annual(annual_net_taxable: float) -> float:
    """Apply progressive brackets to annual taxable income."""
    if annual_net_taxable <= 0:
        return 0
    tax = 0.0
    prev = 0
    for top, rate in PPH21_BRACKETS:
        if annual_net_taxable > top:
            tax += (top - prev) * rate
            prev = top
        else:
            tax += (annual_net_taxable - prev) * rate
            break
    return round(tax)


def compute_pph21_monthly(
    monthly_gross: float,
    ptkp_code: str = "TK/0",
    bpjs_employee_annual: float = 0,
) -> Dict:
    """
    Calculate PPh21 monthly deduction.
    Args:
        monthly_gross: Gaji bruto bulanan (sebelum potongan)
        ptkp_code: Kode PTKP (TK/0, K/1, dst)
        bpjs_employee_annual: BPJS employee contribution setahun (pengurang pajak)

    Returns: { 'pph21_monthly', 'pph21_annual', 'ptkp', 'taxable_annual',
               'biaya_jabatan_monthly', 'breakdown' }
    """
    ptkp = PTKP_ANNUAL.get(ptkp_code, PTKP_ANNUAL["TK/0"])
    annual_gross = monthly_gross * 12
    biaya_jabatan_monthly = compute_biaya_jabatan_monthly(monthly_gross)
    biaya_jabatan_annual = biaya_jabatan_monthly * 12

    # Net income = gross - biaya jabatan - JHT employee - JP employee (pengurang)
    net_annual = annual_gross - biaya_jabatan_annual - bpjs_employee_annual
    taxable = max(0, net_annual - ptkp)
    pph_annual = compute_pph21_annual(taxable)
    pph_monthly = round(pph_annual / 12)

    return {
        "pph21_monthly": pph_monthly,
        "pph21_annual": pph_annual,
        "ptkp_code": ptkp_code,
        "ptkp_annual": ptkp,
        "annual_gross": annual_gross,
        "biaya_jabatan_monthly": round(biaya_jabatan_monthly),
        "biaya_jabatan_annual": round(biaya_jabatan_annual),
        "bpjs_pengurang_annual": bpjs_employee_annual,
        "net_taxable_annual": round(net_annual),
        "taxable_after_ptkp": round(taxable),
    }


# ─── BPJS ────────────────────────────────────────────────────────────────────
def compute_bpjs(
    monthly_gross: float,
    include_ketenagakerjaan: bool = True,
    jkk_risk_tier: str = "very_low",
    *,
    programs: Optional[Dict[str, bool]] = None,
    cfg: Optional[Dict] = None,
) -> Dict:
    """
    Calculate BPJS deductions (Kesehatan + Ketenagakerjaan).

    2026-11-02 (K22/K23):
      `programs` = kepesertaan {kes, jht, jp, jkk_jkm}; None = perilaku lama (Kes selalu,
                   JHT/JP/JKK/JKM bila include_ketenagakerjaan).
      `cfg`      = setelan dari rahaza_payroll_settings (merge_bpjs_config); None = konstanta bawaan.
                   Kelas risiko JKK diambil dari cfg["jkk_risk_tier"] bila cfg diberikan.

    Returns keys:
      kes_emp, kes_comp (BPJS Kesehatan)
      jht_emp, jht_comp (Jaminan Hari Tua)
      jp_emp, jp_comp   (Jaminan Pensiun)
      jkk_comp, jkm_comp (Kecelakaan Kerja, Kematian — company only)
      total_employee: total potongan dari karyawan (masuk deductions)
      total_company:  total kontribusi perusahaan (cost, bukan potongan)
    """
    if programs is None:
        programs = {"kes": True, "jht": include_ketenagakerjaan, "jp": include_ketenagakerjaan,
                    "jkk_jkm": include_ketenagakerjaan}
    c = merge_bpjs_config(cfg) if cfg is not None else default_bpjs_config()
    if cfg is None:
        c["jkk_risk_tier"] = jkk_risk_tier
    r, ceil = c["rates"], c["ceilings"]

    kes_emp = kes_comp = jht_emp = jht_comp = jp_emp = jp_comp = jkk_comp = jkm_comp = 0

    if programs.get("kes"):
        # BPJS Kesehatan (plafon)
        kes_base = min(monthly_gross, ceil["kes"])
        kes_emp = round(kes_base * r["kes_emp"])
        kes_comp = round(kes_base * r["kes_comp"])

    if programs.get("jht"):
        # JHT — tanpa plafon
        jht_emp = round(monthly_gross * r["jht_emp"])
        jht_comp = round(monthly_gross * r["jht_comp"])

    if programs.get("jp"):
        # JP — dengan plafon
        jp_base = min(monthly_gross, ceil["jp"])
        jp_emp = round(jp_base * r["jp_emp"])
        jp_comp = round(jp_base * r["jp_comp"])

    if programs.get("jkk_jkm"):
        # JKK (perusahaan saja, per kelas risiko) + JKM (perusahaan saja)
        jkk_rate = c["jkk_rates"].get(c["jkk_risk_tier"], c["jkk_rates"].get("very_low", 0))
        jkk_comp = round(monthly_gross * jkk_rate)
        jkm_comp = round(monthly_gross * r["jkm_comp"])

    total_employee = kes_emp + jht_emp + jp_emp
    total_company = kes_comp + jht_comp + jp_comp + jkk_comp + jkm_comp

    return {
        "kes_emp": kes_emp,
        "kes_comp": kes_comp,
        "jht_emp": jht_emp,
        "jht_comp": jht_comp,
        "jp_emp": jp_emp,
        "jp_comp": jp_comp,
        "jkk_comp": jkk_comp,
        "jkm_comp": jkm_comp,
        "total_employee": total_employee,
        "total_company": total_company,
        # 2026-11-02 (K22): pembagian per LEMBAGA untuk jurnal & tombol Bayar BPJS.
        "kes_company": kes_comp,
        "tk_company": jht_comp + jp_comp + jkk_comp + jkm_comp,
        "jkk_risk_tier": c["jkk_risk_tier"],
    }


def _pct(rate: float) -> str:
    return f"{float(rate) * 100:g}%".replace(".", ",")


def compute_full_tax_and_bpjs(
    monthly_gross: float,
    ptkp_code: str = "TK/0",
    apply_bpjs: bool = True,
    apply_pph21: bool = True,
    include_ketenagakerjaan: bool = True,
    jkk_risk_tier: str = "very_low",
    bpjs_base: float | None = None,
    *,
    programs: Optional[Dict[str, bool]] = None,
    bpjs_cfg: Optional[Dict] = None,
) -> Dict:
    """
    One-shot calculator.
    Returns a list of 'deductions' [{label, amount, type}] + the raw calc.

    2026-11-02 (K22/K23): `programs` & `bpjs_cfg` diteruskan ke compute_bpjs (lihat di sana).

    FASE 15 — `bpjs_base`: dasar iuran BPJS adalah **UPAH TETAP** (gaji pokok +
    tunjangan TETAP), bukan penghasilan bruto. Rujukan: PP 84/2013 jo. Perpres
    64/2020, dan ini juga cara hitung di sheet "Data THP" milik user:
    1% × (Gaji Pokok + Tunjangan Jabatan). Kalau `bpjs_base` tidak diberikan,
    perilaku lama dipertahankan (memakai `monthly_gross`) supaya tidak ada
    perubahan diam-diam pada pemanggil lain.
    PPh21 TETAP memakai `monthly_gross` (seluruh penghasilan) sesuai UU PPh.
    """
    base_for_bpjs = monthly_gross if bpjs_base is None else float(bpjs_base)
    bpjs = compute_bpjs(base_for_bpjs, include_ketenagakerjaan, jkk_risk_tier,
                        programs=programs, cfg=bpjs_cfg) if apply_bpjs else {
        "kes_emp": 0, "jht_emp": 0, "jp_emp": 0, "total_employee": 0, "total_company": 0,
        "kes_company": 0, "tk_company": 0,
    }
    rates = (merge_bpjs_config(bpjs_cfg) if bpjs_cfg is not None else default_bpjs_config())["rates"]

    bpjs_emp_annual = bpjs["total_employee"] * 12
    pph21 = compute_pph21_monthly(monthly_gross, ptkp_code, bpjs_emp_annual) if apply_pph21 else {
        "pph21_monthly": 0, "pph21_annual": 0,
    }

    deductions = []
    # 2026-11-02 (K23): baris potongan mengikuti hasil compute_bpjs (yang sudah memperhitungkan
    # kepesertaan per program); label memakai tarif yang berlaku, bukan teks tetap.
    if apply_bpjs and bpjs["kes_emp"] > 0:
        deductions.append({"label": f"BPJS Kesehatan ({_pct(rates['kes_emp'])})", "amount": bpjs["kes_emp"],
                           "type": "bpjs_kesehatan"})
    if apply_bpjs and (include_ketenagakerjaan or programs is not None):
        if bpjs["jht_emp"] > 0:
            deductions.append({"label": f"BPJS Ketenagakerjaan JHT ({_pct(rates['jht_emp'])})",
                               "amount": bpjs["jht_emp"], "type": "bpjs_jht"})
        if bpjs["jp_emp"] > 0:
            deductions.append({"label": f"BPJS Ketenagakerjaan JP ({_pct(rates['jp_emp'])})",
                               "amount": bpjs["jp_emp"], "type": "bpjs_jp"})
    if apply_pph21 and pph21["pph21_monthly"] > 0:
        deductions.append({"label": f"PPh21 ({ptkp_code})", "amount": pph21["pph21_monthly"], "type": "pph21"})

    return {
        "deductions": deductions,
        "bpjs": bpjs,
        "pph21": pph21,
        "total_deductions": sum(d["amount"] for d in deductions),
    }
