"""rahaza_payroll_settings.py — ATURAN POTONGAN TERLAMBAT & BONUS KEHADIRAN.

FASE 15 (2026-07-26). Sheet "Data THP" milik user punya kolom **POTONGAN
TERLAMBAT** dan **BONUS KEHADIRAN**, tapi sistem sama sekali tidak punya
tempat menyimpan ATURANNYA. Menaruh angka di kode = HR tidak bisa mengubahnya
dan agent berikutnya akan menebak-nebak.

Prinsip yang dipegang (pelajaran FASE 12 BUG-B):
  **Kalau aturannya belum diisi, sistem TIDAK memotong apa pun.**
  Lebih baik tidak memotong daripada memotong dengan angka karangan.

Disimpan di `rahaza_payroll_settings` dengan `key` sebagai penanda dokumen
(pola SSOT yang sama seperti `rahaza_costing_settings`) — tidak menambah
koleksi baru per-fitur.

2026-11-02 — keputusan owner (TANPA koleksi/layar ganda; semua di koleksi yang sama ini):
  key "bpjs"      (K22/K23) tarif & plafon per program, kelas risiko JKK, saklar jurnal iuran
                  perusahaan (bawaan MATI sampai owner menyalakan). Bawaan = konstanta rahaza_payroll_tax.
  key "overtime"  (K24) aturan CADANGAN bila tarif lembur Profil Gaji = 0:
                  1/173 × upah tetap, jam ke-1 × 1,5, jam berikutnya × 2 (pengali bisa diatur).
  key "kasbon"    (K25) batas kasbon: % gaji pokok & maks cicilan. Bawaan 0 = TANPA batas.
2026-11-06 (Tahap 2) — masih di koleksi & layar yang SAMA:
  key "work_calendar" hari kerja per minggu (bawaan 6) — SATU aturan hari kerja (core.workdays).
  key "pph21"         PPh21 metode TER: PTKP, tarif progresif, tabel TER A/B/C, tambahan tanpa NPWP
                      (bawaan = rahaza_payroll_tax.default_pph21_config, sumber hukum dicatat di sana).
  key "overtime"      ditambah tingkatan hari istirahat/libur (PP 35/2021).
  key "attendance_bonus" aturan hangus per jenis (alpa, izin tanpa surat, terlambat hari/menit) kini
                      DITERAPKAN mesin hitung ke tunjangan bonus kehadiran.
Layar: tab "Pengaturan Payroll" di hub Penggajian (RahazaPayrollSettingsModule.jsx).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from auth import log_activity, serialize_doc
from database import get_db
from core.roles import FINANCE_ROLES
from core.workdays import DEFAULT_WORK_DAYS_PER_WEEK, WORK_CALENDAR_KEY
from routes.rahaza_payroll_shared import PAYROLL_HR_ROLES, _require_hr
from routes.rahaza_payroll_tax import (BPJS_JKK_RATES, default_bpjs_config, default_pph21_config,
                                       merge_bpjs_config, merge_pph21_config)

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-payroll-settings"])

LATE_KEY = "late_penalty"
ATT_BONUS_KEY = "attendance_bonus"
BPJS_KEY = "bpjs"
OVERTIME_KEY = "overtime"
KASBON_KEY = "kasbon"
PPH21_KEY = "pph21"

# Saklar jurnal iuran perusahaan: "sampai owner menyalakan" → hanya owner/superadmin yang boleh mengubah.
SWITCH_ROLES = ("owner", "superadmin")

DEFAULT_BPJS = {
    "key": BPJS_KEY,
    **default_bpjs_config(),
    "employer_contribution_journal": False,   # SENGAJA mati sampai owner menyalakan (K22)
    "note": ("Tarif bawaan = tarif sistem lama. Iuran perusahaan tetap DIHITUNG dan tampil di slip; "
             "jurnalnya (Dr 6-3200/6-3300 / Cr 2-1501/2-1502) baru dibuat bila saklar dinyalakan owner."),
}

OVERTIME_BASES = ("upah_tetap_div_173", "manual")
DEFAULT_OVERTIME = {
    "key": OVERTIME_KEY,
    "basis": "upah_tetap_div_173",   # keputusan owner K24: cadangan bila tarif Profil Gaji = 0
    "divisor": 173,
    "first_hour_multiplier": 1.5,
    "next_hours_multiplier": 2.0,
    # 2026-11-06 (Tahap 2): hari istirahat mingguan / libur resmi — PP 35/2021 Pasal 31.
    "rest_day_first_hours_6d": 7,
    "rest_day_first_hours_5d": 8,
    "rest_day_first_multiplier": 2.0,
    "rest_day_next_hour_multiplier": 3.0,
    "rest_day_after_multiplier": 4.0,
    "note": ("Tarif lembur per Profil Gaji tetap dipakai bila > 0. Bila 0: 1/173 × upah tetap "
             "(gaji pokok bulanan + tunjangan tetap), jam ke-1 × 1,5, jam berikutnya × 2. "
             "Hanya untuk skema bulanan; skema lain tanpa tarif profil diberi peringatan di run gaji. "
             "basis 'manual' = tanpa cadangan (lembur bertarif 0 tidak dibayar, hanya diperingatkan)."),
}

DEFAULT_KASBON = {
    "key": KASBON_KEY,
    "max_pct_of_base_salary": 0,   # 0 = tanpa batas (bawaan sampai owner mengisi)
    "max_installments": 0,         # 0 = tanpa batas
    "note": ("Batas berlaku untuk pengajuan baru dan saat HR menyetujui. Nilai 0 = tanpa batas. "
             "Gaji pokok = Profil Gaji aktif skema bulanan."),
}


async def get_bpjs_settings(db) -> dict:
    """Setelan BPJS yang berlaku (bawaan digabung dengan dokumen tersimpan)."""
    doc = await db.rahaza_payroll_settings.find_one({"key": BPJS_KEY}, {"_id": 0}) or {}
    out = {**DEFAULT_BPJS, **merge_bpjs_config(doc)}
    out["employer_contribution_journal"] = bool(doc.get("employer_contribution_journal", False))
    for k in ("updated_at", "updated_by", "updated_by_name"):
        if k in doc:
            out[k] = doc[k]
    return out


async def get_overtime_settings(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": OVERTIME_KEY}, {"_id": 0}) or {}
    return {**DEFAULT_OVERTIME, **doc}


async def get_kasbon_settings(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": KASBON_KEY}, {"_id": 0}) or {}
    return {**DEFAULT_KASBON, **doc}


async def get_attendance_bonus_settings(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": ATT_BONUS_KEY}, {"_id": 0}) or {}
    out = {**DEFAULT_ATT_BONUS, **doc}
    if "forfeit_if_alpa" not in doc and "require_full_attendance" in doc:
        out["forfeit_if_alpa"] = bool(doc["require_full_attendance"])
    return out


async def get_pph21_settings(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": PPH21_KEY}, {"_id": 0}) or {}
    out = {"key": PPH21_KEY, **merge_pph21_config(doc)}
    for k in ("updated_at", "updated_by", "updated_by_name"):
        if k in doc:
            out[k] = doc[k]
    return out


async def get_work_calendar_settings(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": WORK_CALENDAR_KEY}, {"_id": 0}) or {}
    return {**DEFAULT_WORK_CALENDAR, **doc}


async def _require_hr_or_finance(request: Request):
    """PPh21: diubah HR ATAU Keuangan (keputusan owner Tahap 2). Gerbang konfigurasi payroll lain tetap
    PAYROLL_HR_ROLES."""
    from auth import require_auth
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    perms = user.get("_permissions") or []
    if role in PAYROLL_HR_ROLES or role in FINANCE_ROLES or "*" in perms or "payroll.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: pengaturan PPh21 hanya untuk HR atau Keuangan.")

VALID_LATE_MODES = ("per_minute", "tiered", "per_occurrence")

DEFAULT_LATE = {
    "key": LATE_KEY,
    "enabled": False,           # SENGAJA mati sampai HR mengisi aturannya
    "mode": "per_minute",
    "amount_per_minute": 0,
    "amount_per_occurrence": 0,
    "tiers": [],                # [{from_minutes, to_minutes|None, amount}]
    "note": ("Isi aturan lalu aktifkan. Selama 'enabled' = false, sistem TIDAK "
             "memotong keterlambatan sama sekali."),
}

# 2026-11-06 (Tahap 2): aturan hangus kini DITERAPKAN (dulu tersimpan tetapi diabaikan — 18 slip membayar
# bonus dengan 0 hari hadir). Bawaan `enabled` = True; tunjangan yang dianggap bonus kehadiran =
# `allowance_ids` (kosong → template tunjangan bernama "...kehadiran...").
DEFAULT_ATT_BONUS = {
    "key": ATT_BONUS_KEY,
    "enabled": True,
    "amount": 0,
    "allowance_ids": [],
    "forfeit_if_alpa": True,           # hangus bila alpa > max_alpa_days
    "max_alpa_days": 0,
    "require_full_attendance": True,   # nama lama forfeit_if_alpa (tetap dibaca)
    "forfeit_if_izin_no_note": True,   # izin/sakit tanpa surat / tanpa pengajuan disetujui
    "max_izin_no_note_days": 0,
    "forfeit_if_late": True,           # hangus bila hari terlambat > max_late_days_allowed
    "max_late_days_allowed": 0,
    "late_minutes_limit": 0,           # 0 = aturan menit tidak dipakai
    "min_days_present": 0,
    "note": ("Bonus kehadiran diberikan lewat template tunjangan; aturan di sini "
             "menentukan kapan bonus itu HANGUS."),
}

DEFAULT_WORK_CALENDAR = {
    "key": WORK_CALENDAR_KEY,
    "work_days_per_week": DEFAULT_WORK_DAYS_PER_WEEK,
    "note": "Hari kerja per minggu (6 = Senin–Sabtu). Hari libur dari Kalender Produksi.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get(db, key: str, default: dict) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": key}, {"_id": 0})
    return doc or dict(default)


@router.get("/payroll-settings/late-penalty")
async def get_late_penalty(request: Request):
    await _require_hr(request)
    return serialize_doc(await _get(get_db(), LATE_KEY, DEFAULT_LATE))


@router.put("/payroll-settings/late-penalty")
async def set_late_penalty(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()

    mode = (body.get("mode") or "per_minute").strip()
    if mode not in VALID_LATE_MODES:
        raise HTTPException(400, f"mode harus salah satu: {list(VALID_LATE_MODES)}")

    tiers = []
    for t in (body.get("tiers") or []):
        try:
            frm = int(t.get("from_minutes") or 0)
            to = t.get("to_minutes")
            to = int(to) if to not in (None, "") else None
            amt = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "tiers harus berisi angka (from_minutes/to_minutes/amount).")
        if frm < 0 or amt < 0 or (to is not None and to < frm):
            raise HTTPException(400, "Rentang tier tidak valid (to_minutes < from_minutes atau nilai negatif).")
        tiers.append({"from_minutes": frm, "to_minutes": to, "amount": amt})

    apm = float(body.get("amount_per_minute") or 0)
    apo = float(body.get("amount_per_occurrence") or 0)
    if apm < 0 or apo < 0:
        raise HTTPException(400, "Nominal potongan tidak boleh negatif.")

    enabled = bool(body.get("enabled"))
    if enabled:
        if mode == "per_minute" and apm <= 0:
            raise HTTPException(400, "mode 'per_minute' aktif tapi amount_per_minute masih 0.")
        if mode == "per_occurrence" and apo <= 0:
            raise HTTPException(400, "mode 'per_occurrence' aktif tapi amount_per_occurrence masih 0.")
        if mode == "tiered" and not tiers:
            raise HTTPException(400, "mode 'tiered' aktif tapi belum ada tier.")

    doc = {
        "key": LATE_KEY,
        "enabled": enabled,
        "mode": mode,
        "amount_per_minute": apm,
        "amount_per_occurrence": apo,
        "tiers": tiers,
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    }
    await db.rahaza_payroll_settings.update_one({"key": LATE_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update",
                       "rahaza.payroll_settings", LATE_KEY)
    return serialize_doc({"ok": True, "settings": doc})


@router.get("/payroll-settings/attendance-bonus")
async def get_attendance_bonus(request: Request):
    await _require_hr(request)
    return serialize_doc(await get_attendance_bonus_settings(get_db()))


@router.put("/payroll-settings/attendance-bonus")
async def set_attendance_bonus(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    try:
        amount = float(body.get("amount") or 0)
        max_late = int(body.get("max_late_days_allowed") or 0)
        min_days = int(body.get("min_days_present") or 0)
        max_alpa = float(body.get("max_alpa_days") or 0)
        max_izin = int(body.get("max_izin_no_note_days") or 0)
        late_min = int(body.get("late_minutes_limit") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Batas hari/menit dan nominal harus angka.")
    if min(amount, max_late, min_days, max_alpa, max_izin, late_min) < 0:
        raise HTTPException(400, "Nilai tidak boleh negatif.")
    ids = body.get("allowance_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(400, "allowance_ids harus daftar.")
    forfeit_alpa = bool(body.get("forfeit_if_alpa", body.get("require_full_attendance", True)))

    doc = {
        "key": ATT_BONUS_KEY,
        "enabled": bool(body.get("enabled", True)),
        "amount": amount,
        "allowance_ids": [str(x) for x in ids if x],
        "forfeit_if_alpa": forfeit_alpa,
        "require_full_attendance": forfeit_alpa,
        "max_alpa_days": max_alpa,
        "forfeit_if_izin_no_note": bool(body.get("forfeit_if_izin_no_note", True)),
        "max_izin_no_note_days": max_izin,
        "forfeit_if_late": bool(body.get("forfeit_if_late", True)),
        "max_late_days_allowed": max_late,
        "late_minutes_limit": late_min,
        "min_days_present": min_days,
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    }
    await db.rahaza_payroll_settings.update_one({"key": ATT_BONUS_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update",
                       "rahaza.payroll_settings", ATT_BONUS_KEY)
    return serialize_doc({"ok": True, "settings": doc})


def _num(body: dict, field: str, *, lo: float = 0.0, hi: Optional[float] = None, default=0.0) -> float:
    raw = body.get(field, default)
    try:
        val = float(raw if raw not in (None, "") else default)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} harus angka.")
    if val < lo or (hi is not None and val > hi):
        rng = f"{lo:g}–{hi:g}" if hi is not None else f"≥ {lo:g}"
        raise HTTPException(400, f"{field} di luar rentang yang wajar ({rng}).")
    return val


def _audit(user: dict) -> dict:
    return {"updated_at": _now(), "updated_by": user["id"], "updated_by_name": user.get("name", "")}


# ─── BPJS (K22/K23, 2026-11-02) ───────────────────────────────────────────────
@router.get("/payroll-settings/bpjs")
async def get_bpjs(request: Request):
    await _require_hr(request)
    return serialize_doc(await get_bpjs_settings(get_db()))


@router.put("/payroll-settings/bpjs")
async def set_bpjs(request: Request):
    """Tarif (desimal, mis. 0.01 = 1%), plafon (Rp), kelas risiko JKK, saklar jurnal iuran perusahaan.

    Saklar `employer_contribution_journal` hanya boleh DIUBAH owner/superadmin (keputusan owner:
    "bawaan mati sampai owner menyalakan"); HR tetap boleh menyimpan tarif tanpa menyentuh saklar."""
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    cur = await get_bpjs_settings(db)
    base = default_bpjs_config()

    rates_in = body.get("rates") or {}
    rates = {}
    for k in base["rates"]:
        rates[k] = _num(rates_in, k, hi=0.2, default=cur["rates"][k])
    ceilings_in = body.get("ceilings") or {}
    ceilings = {k: _num(ceilings_in, k, default=cur["ceilings"][k]) for k in base["ceilings"]}
    jkk_in = body.get("jkk_rates") or {}
    jkk_rates = {k: _num(jkk_in, k, hi=0.2, default=cur["jkk_rates"].get(k, v)) for k, v in BPJS_JKK_RATES.items()}
    tier = (body.get("jkk_risk_tier") or cur.get("jkk_risk_tier") or "very_low").strip()
    if tier not in jkk_rates:
        raise HTTPException(400, f"jkk_risk_tier harus salah satu: {list(jkk_rates)}")

    switch = bool(body.get("employer_contribution_journal", cur["employer_contribution_journal"]))
    if switch != cur["employer_contribution_journal"] and (user.get("role") or "").lower() not in SWITCH_ROLES:
        raise HTTPException(403, "Saklar jurnal iuran BPJS perusahaan hanya boleh diubah owner.")

    doc = {"key": BPJS_KEY, "rates": rates, "ceilings": ceilings, "jkk_rates": jkk_rates,
           "jkk_risk_tier": tier, "employer_contribution_journal": switch, **_audit(user)}
    await db.rahaza_payroll_settings.update_one({"key": BPJS_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.payroll_settings",
                       f"{BPJS_KEY} jkk={tier} jurnal_perusahaan={'ON' if switch else 'OFF'}")
    return serialize_doc({"ok": True, "settings": await get_bpjs_settings(db)})


# ─── LEMBUR (K24, 2026-11-02) ─────────────────────────────────────────────────
@router.get("/payroll-settings/overtime")
async def get_overtime(request: Request):
    await _require_hr(request)
    return serialize_doc(await get_overtime_settings(get_db()))


@router.put("/payroll-settings/overtime")
async def set_overtime(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    basis = (body.get("basis") or "upah_tetap_div_173").strip()
    if basis not in OVERTIME_BASES:
        raise HTTPException(400, f"basis harus salah satu: {list(OVERTIME_BASES)}")
    doc = {
        "key": OVERTIME_KEY, "basis": basis,
        "divisor": _num(body, "divisor", lo=1, hi=400, default=173),
        "first_hour_multiplier": _num(body, "first_hour_multiplier", lo=1, hi=10, default=1.5),
        "next_hours_multiplier": _num(body, "next_hours_multiplier", lo=1, hi=10, default=2.0),
        # 2026-11-06 (Tahap 2): hari istirahat/libur resmi (PP 35/2021)
        "rest_day_first_hours_6d": _num(body, "rest_day_first_hours_6d", lo=1, hi=12, default=7),
        "rest_day_first_hours_5d": _num(body, "rest_day_first_hours_5d", lo=1, hi=12, default=8),
        "rest_day_first_multiplier": _num(body, "rest_day_first_multiplier", lo=1, hi=10, default=2.0),
        "rest_day_next_hour_multiplier": _num(body, "rest_day_next_hour_multiplier", lo=1, hi=10, default=3.0),
        "rest_day_after_multiplier": _num(body, "rest_day_after_multiplier", lo=1, hi=10, default=4.0),
        **_audit(user),
    }
    await db.rahaza_payroll_settings.update_one({"key": OVERTIME_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.payroll_settings", OVERTIME_KEY)
    return serialize_doc({"ok": True, "settings": await get_overtime_settings(db)})


# ─── BATAS KASBON (K25, 2026-11-02) ───────────────────────────────────────────
@router.get("/payroll-settings/kasbon")
async def get_kasbon(request: Request):
    await _require_hr(request)
    return serialize_doc(await get_kasbon_settings(get_db()))


@router.put("/payroll-settings/kasbon")
async def set_kasbon(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    doc = {
        "key": KASBON_KEY,
        "max_pct_of_base_salary": _num(body, "max_pct_of_base_salary", hi=1000),
        "max_installments": int(_num(body, "max_installments", hi=120)),
        **_audit(user),
    }
    await db.rahaza_payroll_settings.update_one({"key": KASBON_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.payroll_settings", KASBON_KEY)
    return serialize_doc({"ok": True, "settings": await get_kasbon_settings(db)})


# ─── KALENDER KERJA (Tahap 2, 2026-11-06) ─────────────────────────────────────
@router.get("/payroll-settings/work-calendar")
async def get_work_calendar_endpoint(request: Request):
    await _require_hr(request)
    return serialize_doc(await get_work_calendar_settings(get_db()))


@router.put("/payroll-settings/work-calendar")
async def set_work_calendar(request: Request):
    """Hari kerja per minggu (1–7, bawaan 6). Dipakai SEMUA hitungan hari kerja (core.workdays)."""
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    n = int(_num(body, "work_days_per_week", lo=1, hi=7, default=DEFAULT_WORK_DAYS_PER_WEEK))
    doc = {"key": WORK_CALENDAR_KEY, "work_days_per_week": n, **_audit(user)}
    await db.rahaza_payroll_settings.update_one({"key": WORK_CALENDAR_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.payroll_settings",
                       f"{WORK_CALENDAR_KEY} {n} hari/minggu")
    return serialize_doc({"ok": True, "settings": await get_work_calendar_settings(db)})


# ─── PPh21 (Tahap 2, 2026-11-06) ──────────────────────────────────────────────
@router.get("/payroll-settings/pph21")
async def get_pph21(request: Request):
    await _require_hr_or_finance(request)
    return serialize_doc(await get_pph21_settings(get_db()))


@router.put("/payroll-settings/pph21")
async def set_pph21(request: Request):
    """PTKP, tarif progresif, tabel TER A/B/C, kategori TER per PTKP, biaya jabatan, tambahan tanpa NPWP.
    Bagian yang tidak dikirim = nilai sekarang. `reset: true` = kembali ke bawaan peraturan."""
    user = await _require_hr_or_finance(request)
    db = get_db()
    body = await request.json()
    keys = set(default_pph21_config())
    if body.get("reset"):
        base = default_pph21_config()
    else:
        cur = await get_pph21_settings(db)
        base = {k: v for k, v in cur.items() if k in keys}
        base.update({k: v for k, v in body.items() if k in keys})
    try:
        cfg = merge_pph21_config(base, strict=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    doc = {"key": PPH21_KEY, **cfg, **_audit(user)}
    await db.rahaza_payroll_settings.update_one({"key": PPH21_KEY}, {"$set": doc}, upsert=True)
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.payroll_settings",
                       f"{PPH21_KEY} {'aktif' if cfg['enabled'] else 'mati'}")
    return serialize_doc({"ok": True, "settings": await get_pph21_settings(db)})


@router.get("/payroll-settings")
async def list_settings(request: Request, key: Optional[str] = None):
    """Semua pengaturan payroll (untuk panel HR — tab "Pengaturan Payroll")."""
    user = await _require_hr(request)
    db = get_db()
    loaders = {
        LATE_KEY: lambda: _get(db, LATE_KEY, DEFAULT_LATE),
        ATT_BONUS_KEY: lambda: get_attendance_bonus_settings(db),
        BPJS_KEY: lambda: get_bpjs_settings(db),
        OVERTIME_KEY: lambda: get_overtime_settings(db),
        KASBON_KEY: lambda: get_kasbon_settings(db),
        WORK_CALENDAR_KEY: lambda: get_work_calendar_settings(db),
        PPH21_KEY: lambda: get_pph21_settings(db),
    }
    if key:
        if key not in loaders:
            raise HTTPException(404, f"Kunci pengaturan '{key}' tidak dikenal: {list(loaders)}")
        return serialize_doc(await loaders[key]())
    out = {"ok": True, "can_toggle_bpjs_journal": (user.get("role") or "").lower() in SWITCH_ROLES}
    for k, fn in loaders.items():
        out[k] = await fn()
    return serialize_doc(out)
