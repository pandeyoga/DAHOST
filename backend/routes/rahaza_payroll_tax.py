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
    JP  (Pensiun):  3%   = 1% employee + 2%   employer (plafon upah berjadwal, lihat BPJS_JP_CEILING_SCHEDULE)
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

# 2026-11-09 (M4, audit HR): plafon upah Jaminan Pensiun naik tiap 1 Maret (PP 45/2015 Ps 5: disesuaikan dengan
# pertumbuhan PDB). Dulu satu angka 2024 (10.042.300) selamanya → JP gaji > Rp10 juta kurang dipotong.
#   · 1 Mar 2024 Rp10.042.300 · 1 Mar 2025 Rp10.547.400 (surat informasi BPJS TK batas upah JP 2025)
#   · 1 Mar 2026 Rp11.086.300 (sosialisasi BPJS TK, KEPDIR difinalkan — KONFIRMASI ke surat resmi; bisa diganti di
#     Pengaturan Payroll › BPJS, nilai isian yang bukan angka jadwal ini selalu dipakai apa adanya).
BPJS_JP_CEILING_SCHEDULE = (("2024-03-01", 10_042_300), ("2025-03-01", 10_547_400), ("2026-03-01", 11_086_300))
BPJS_JP_CEILING = BPJS_JP_CEILING_SCHEDULE[-1][1]   # bawaan layar setelan = plafon terbaru


def jp_ceiling_on(day=None) -> int:
    """Plafon upah JP yang berlaku pada tanggal `day` (date/teks ISO; None = plafon terbaru)."""
    if day is None:
        return BPJS_JP_CEILING
    iso = str(day)[:10]
    cur = BPJS_JP_CEILING_SCHEDULE[0][1]
    for start, cap in BPJS_JP_CEILING_SCHEDULE:
        if iso >= start:
            cur = cap
    return cur


def apply_jp_ceiling_schedule(cfg: Dict, day) -> Dict:
    """Setelan BPJS untuk periode bertanggal `day`: plafon JP ikut jadwal resmi bila setelan memakai angka jadwal
    (bawaan lama yang tersimpan saat formulir disimpan); angka lain (diisi HR sendiri) tetap dipakai."""
    out = {**cfg, "ceilings": dict(cfg.get("ceilings") or {})}
    official = {cap for _, cap in BPJS_JP_CEILING_SCHEDULE}
    try:
        cur = float(out["ceilings"].get("jp"))
    except (TypeError, ValueError):
        cur = None
    if cur is None or round(cur) in official:
        out["ceilings"]["jp"] = jp_ceiling_on(day)
    return out


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


# ═══════════════════════════════════════════════════════════════════════════════
# PPh21 METODE TER — 2026-11-06 (Tahap 2, keputusan owner: tarif, PTKP, tabel TER bisa diatur)
# ═══════════════════════════════════════════════════════════════════════════════
# Nilai di bawah hanya BAWAAN; yang berlaku dibaca dari `rahaza_payroll_settings` key "pph21"
# (layar Pengaturan Payroll) lewat merge_pph21_config(). Sumber:
#   · PTKP           : PMK 101/PMK.010/2016 (masih berlaku menurut UU 7/2021 HPP).
#   · Tarif Pasal 17 : UU 7/2021 (HPP) — 5% / 15% / 25% / 30% / 35%.
#   · TER bulanan A/B/C : Lampiran PP 58/2023, tata cara PMK 168/2023 (berlaku 1 Jan 2024).
#     A = TK/0, TK/1, K/0 · B = TK/2, TK/3, K/1, K/2 · C = K/3.
#   · Masa pajak Desember (atau bulan terakhir bekerja): PPh21 setahun dengan tarif Pasal 17 dikurangi
#     PPh21 TER Januari–November (PMK 168/2023).
#   · Biaya jabatan 5%, maks Rp500.000 per bulan / Rp6.000.000 per tahun.
#   · Iuran JHT & JP yang dibayar KARYAWAN = pengurang penghasilan bruto. Iuran BPJS Kesehatan karyawan
#     BUKAN pengurang. Premi JKK, JKM, dan BPJS Kesehatan yang dibayar perusahaan = penghasilan (bruto).
#   · Sejak 2024 NIK = NPWP (PMK 112/2022) → tambahan 20% bagi yang tidak ber-NPWP bawaan MATI.
# Tabel ditulis [batas_atas_bruto_bulanan, tarif]; batas_atas None = selebihnya.
TER_A = [
    [5_400_000, 0], [5_650_000, 0.0025], [5_950_000, 0.005], [6_300_000, 0.0075], [6_750_000, 0.01],
    [7_500_000, 0.0125], [8_550_000, 0.015], [9_650_000, 0.0175], [10_050_000, 0.02], [10_350_000, 0.0225],
    [10_700_000, 0.025], [11_050_000, 0.03], [11_600_000, 0.035], [12_500_000, 0.04], [13_750_000, 0.05],
    [15_100_000, 0.06], [16_950_000, 0.07], [19_750_000, 0.08], [24_150_000, 0.09], [26_450_000, 0.10],
    [28_000_000, 0.11], [30_050_000, 0.12], [32_400_000, 0.13], [35_400_000, 0.14], [39_100_000, 0.15],
    [43_850_000, 0.16], [47_800_000, 0.17], [51_400_000, 0.18], [56_300_000, 0.19], [62_200_000, 0.20],
    [68_600_000, 0.21], [77_500_000, 0.22], [89_000_000, 0.23], [103_000_000, 0.24], [125_000_000, 0.25],
    [157_000_000, 0.26], [206_000_000, 0.27], [337_000_000, 0.28], [454_000_000, 0.29], [550_000_000, 0.30],
    [695_000_000, 0.31], [910_000_000, 0.32], [1_400_000_000, 0.33], [None, 0.34],
]
TER_B = [
    [6_200_000, 0], [6_500_000, 0.0025], [6_850_000, 0.005], [7_300_000, 0.0075], [9_200_000, 0.01],
    [10_750_000, 0.015], [11_250_000, 0.02], [11_600_000, 0.025], [12_600_000, 0.03], [13_600_000, 0.04],
    [14_950_000, 0.05], [16_400_000, 0.06], [18_450_000, 0.07], [21_850_000, 0.08], [26_000_000, 0.09],
    [27_700_000, 0.10], [29_350_000, 0.11], [31_450_000, 0.12], [33_950_000, 0.13], [37_100_000, 0.14],
    [41_100_000, 0.15], [45_800_000, 0.16], [49_500_000, 0.17], [53_800_000, 0.18], [58_500_000, 0.19],
    [64_000_000, 0.20], [71_000_000, 0.21], [80_000_000, 0.22], [93_000_000, 0.23], [109_000_000, 0.24],
    [129_000_000, 0.25], [163_000_000, 0.26], [211_000_000, 0.27], [374_000_000, 0.28], [459_000_000, 0.29],
    [555_000_000, 0.30], [704_000_000, 0.31], [957_000_000, 0.32], [1_405_000_000, 0.33], [None, 0.34],
]
TER_C = [
    [6_600_000, 0], [6_950_000, 0.0025], [7_350_000, 0.005], [7_800_000, 0.0075], [8_850_000, 0.01],
    [9_800_000, 0.0125], [10_950_000, 0.015], [11_200_000, 0.0175], [12_050_000, 0.02], [12_950_000, 0.03],
    [14_150_000, 0.04], [15_550_000, 0.05], [17_050_000, 0.06], [19_500_000, 0.07], [22_700_000, 0.08],
    [26_600_000, 0.09], [28_100_000, 0.10], [30_100_000, 0.11], [32_600_000, 0.12], [35_400_000, 0.13],
    [38_900_000, 0.14], [43_000_000, 0.15], [47_400_000, 0.16], [51_200_000, 0.17], [55_800_000, 0.18],
    [60_400_000, 0.19], [66_700_000, 0.20], [74_500_000, 0.21], [83_200_000, 0.22], [95_600_000, 0.23],
    [110_000_000, 0.24], [134_000_000, 0.25], [169_000_000, 0.26], [221_000_000, 0.27], [390_000_000, 0.28],
    [463_000_000, 0.29], [561_000_000, 0.30], [709_000_000, 0.31], [965_000_000, 0.32], [1_419_000_000, 0.33],
    [None, 0.34],
]
TER_CATEGORY_BY_PTKP = {"TK/0": "A", "TK/1": "A", "K/0": "A", "TK/2": "B", "TK/3": "B",
                        "K/1": "B", "K/2": "B", "K/3": "C"}


def default_pph21_config() -> Dict:
    return {
        "enabled": True,
        "method": "ter",                               # TER bulanan + perhitungan setahun di Desember
        "ptkp": dict(PTKP_ANNUAL),
        "brackets": [[None if top == float("inf") else top, rate] for top, rate in PPH21_BRACKETS],
        "ter": {"A": [list(r) for r in TER_A], "B": [list(r) for r in TER_B], "C": [list(r) for r in TER_C]},
        "ter_category": dict(TER_CATEGORY_BY_PTKP),
        "biaya_jabatan_rate": BIAYA_JABATAN_RATE,
        "biaya_jabatan_max_month": BIAYA_JABATAN_MAX_ANNUAL / 12,
        "employer_premiums_taxable": True,             # JKK + JKM + BPJS Kes perusahaan masuk bruto
        "december_true_up": True,
        "no_npwp_surcharge_enabled": False,            # NIK = NPWP sejak 2024
        "no_npwp_surcharge_rate": 0.20,
    }


def _clean_table(rows, *, field: str) -> list:
    """[[batas|None, tarif], …] → tervalidasi & urut naik; baris terakhir wajib batas None."""
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            top, rate = r.get("up_to"), r.get("rate")
        else:
            top, rate = (list(r) + [None, None])[:2]
        top = None if top in (None, "", "inf") else float(top)
        rate = float(rate or 0)
        if rate < 0 or rate > 1 or (top is not None and top <= 0):
            raise ValueError(f"{field}: tarif harus 0–100% dan batas harus > 0.")
        out.append([top, rate])
    if not out:
        raise ValueError(f"{field}: tabel kosong.")
    tops = [t for t, _ in out[:-1]]
    if any(t is None for t in tops) or out[-1][0] is not None:
        raise ValueError(f"{field}: hanya baris terakhir yang tanpa batas atas.")
    if tops != sorted(tops) or len(set(tops)) != len(tops):
        raise ValueError(f"{field}: batas atas harus naik.")
    return out


def merge_pph21_config(stored: Optional[Dict], *, strict: bool = False) -> Dict:
    """Setelan tersimpan digabung bawaan. `strict=True` (dipakai PUT) melempar ValueError bila isian salah;
    `strict=False` (dipakai mesin hitung) mengabaikan bagian rusak dan memakai bawaan."""
    cfg = default_pph21_config()
    s = stored or {}
    for k in ("enabled", "employer_premiums_taxable", "december_true_up", "no_npwp_surcharge_enabled"):
        if k in s and s[k] is not None:
            cfg[k] = bool(s[k])
    for k, lo, hi in (("biaya_jabatan_rate", 0, 1), ("biaya_jabatan_max_month", 0, 100_000_000),
                      ("no_npwp_surcharge_rate", 0, 1)):
        if s.get(k) is not None:
            try:
                v = float(s[k])
                if not lo <= v <= hi:
                    raise ValueError(f"{k} di luar rentang {lo}–{hi}.")
                cfg[k] = v
            except (TypeError, ValueError):
                if strict:
                    raise ValueError(f"{k} harus angka {lo}–{hi}.")
    for code, val in (s.get("ptkp") or {}).items():
        try:
            if float(val) < 0:
                raise ValueError
            cfg["ptkp"][str(code).upper()] = float(val)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"PTKP {code} harus angka ≥ 0.")
    for code, cat in (s.get("ter_category") or {}).items():
        if str(cat).upper() in ("A", "B", "C"):
            cfg["ter_category"][str(code).upper()] = str(cat).upper()
        elif strict:
            raise ValueError(f"Kategori TER untuk {code} harus A, B, atau C.")
    try:
        if s.get("brackets"):
            cfg["brackets"] = _clean_table(s["brackets"], field="Tarif progresif")
        for cat in ("A", "B", "C"):
            if (s.get("ter") or {}).get(cat):
                cfg["ter"][cat] = _clean_table(s["ter"][cat], field=f"TER kategori {cat}")
    except ValueError:
        if strict:
            raise
    return cfg


def _digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def valid_tax_id(v) -> bool:
    """NPWP 15 digit (format lama) atau 16 digit (NIK / NPWP baru) — 2026-11-06 (Tahap 2)."""
    return len(_digits(v)) in (15, 16)


def has_tax_id(emp: Optional[Dict]) -> bool:
    """Punya identitas pajak: NPWP 15/16 digit, atau NIK 16 digit (NIK = NPWP sejak 2024)."""
    e = emp or {}
    return valid_tax_id(e.get("npwp_number")) or len(_digits(e.get("ktp_number"))) == 16


def ter_category(ptkp_code: str, cfg: Dict) -> str:
    return (cfg.get("ter_category") or TER_CATEGORY_BY_PTKP).get(str(ptkp_code or "TK/0").upper(), "A")


def ter_rate(monthly_gross: float, category: str, cfg: Dict) -> float:
    table = (cfg.get("ter") or {}).get(category) or TER_A
    g = float(monthly_gross or 0)
    for top, rate in table:
        if top is None or g <= float(top):
            return float(rate)
    return float(table[-1][1])


def progressive_tax(pkp: float, cfg: Dict) -> float:
    """Tarif Pasal 17 atas penghasilan kena pajak setahun (sudah dibulatkan ke bawah ribuan)."""
    pkp = max(0.0, float(pkp or 0))
    tax, prev = 0.0, 0.0
    for top, rate in cfg.get("brackets") or []:
        upper = float("inf") if top is None else float(top)
        if pkp <= prev:
            break
        tax += (min(pkp, upper) - prev) * float(rate)
        prev = upper
    return round(tax)


def pph21_ter_month(month_gross: float, ptkp_code: str, cfg: Dict, *, no_tax_id: bool = False) -> Dict:
    """PPh21 satu masa pajak (bulan) metode TER: tarif efektif × bruto bulan itu."""
    cat = ter_category(ptkp_code, cfg)
    rate = ter_rate(month_gross, cat, cfg)
    tax = round(max(0.0, float(month_gross or 0)) * rate)
    surcharge = bool(no_tax_id and cfg.get("no_npwp_surcharge_enabled"))
    if surcharge:
        tax = round(tax * (1 + float(cfg.get("no_npwp_surcharge_rate") or 0)))
    return {"method": "ter", "category": cat, "rate": rate, "gross": round(float(month_gross or 0)),
            "tax": tax, "surcharge": surcharge}


def pph21_annual(gross_year: float, jht_jp_year: float, ptkp_code: str, months: int, cfg: Dict,
                 *, no_tax_id: bool = False) -> Dict:
    """PPh21 setahun (masa Desember / bulan terakhir bekerja) — tarif Pasal 17."""
    months = max(1, int(months or 1))
    gross_year = max(0.0, float(gross_year or 0))
    bj = min(gross_year * float(cfg.get("biaya_jabatan_rate") or 0),
             float(cfg.get("biaya_jabatan_max_month") or 0) * months)
    neto = gross_year - bj - max(0.0, float(jht_jp_year or 0))
    ptkp = float((cfg.get("ptkp") or PTKP_ANNUAL).get(str(ptkp_code or "TK/0").upper(),
                                                       (cfg.get("ptkp") or PTKP_ANNUAL).get("TK/0", 0)))
    pkp = max(0.0, neto - ptkp)
    pkp = float(int(pkp // 1000) * 1000)                       # dibulatkan ke bawah ribuan
    tax = progressive_tax(pkp, cfg)
    surcharge = bool(no_tax_id and cfg.get("no_npwp_surcharge_enabled"))
    if surcharge:
        tax = round(tax * (1 + float(cfg.get("no_npwp_surcharge_rate") or 0)))
    return {"method": "annual", "gross_year": round(gross_year), "biaya_jabatan": round(bj),
            "jht_jp_year": round(float(jht_jp_year or 0)), "neto": round(neto), "ptkp": round(ptkp),
            "pkp": round(pkp), "months": months, "tax_year": tax, "surcharge": surcharge}
