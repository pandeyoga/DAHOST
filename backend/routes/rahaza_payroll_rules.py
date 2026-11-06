"""rahaza_payroll_rules.py — ATURAN HITUNG GAJI DARI ABSENSI (2026-11-06, Tahap 2).

Satu tempat untuk aturan yang dipakai mesin hitung slip (`rahaza_payroll_shared._compute_payslip_for_employee`)
dan oleh paket absensi (kunci absensi). Sebagian besar fungsi MURNI (tanpa DB) supaya mudah diuji.

Keputusan owner 6 Nov 2026:
  · Potongan gaji hanya untuk ALPA dan izin/sakit/cuti yang TIDAK dibayar (HR memutuskan per pengajuan:
    `pay_decision` paid/unpaid) atau tanpa pengajuan yang disetujui. Pembagi = hari kerja aktif periode
    (kalender kerja `core.workdays`: 6 hari/minggu bawaan, dikurangi libur Kalender Produksi).
  · Hari kerja TANPA catatan absen sama sekali TIDAK dipotong otomatis (konservatif) — hanya diperingatkan.
  · Masuk/keluar di tengah periode = prorata hari kerja.
  · Lembur tanpa pengajuan tidak dibayar otomatis; HR menandai `overtime_paid` di hari itu. Pengali dan
    tingkatan lembur dari Pengaturan Payroll per HARI (PP 35/2021), bukan pilihan pemohon.
  · Absensi tanggal yang sudah masuk run FINAL terkunci (`is_attendance_locked`) — koreksi sesudahnya masuk
    run berikutnya sebagai baris penyesuaian.

Kontrak status absensi (`rahaza_attendance_events.status`): hadir · izin · sakit · cuti · alpa · libur.
Status lama tetap terbaca: `alfa`/`alpha`/`absent` = alpa, `present`/`H` = hadir, `off` = libur.
"""
from __future__ import annotations

from datetime import date, datetime

PRESENT = frozenset({"hadir", "present", "h", "terlambat", "late"})
ABSENT = frozenset({"alpa", "alfa", "alpha", "absent", "absen", "a"})
LEAVE = frozenset({"izin", "sakit", "cuti"})
OFF = frozenset({"libur", "off"})


def _d(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def norm_status(s) -> str:
    v = str(s or "").strip().lower()
    if v in PRESENT:
        return "hadir"
    if v in ABSENT:
        return "alpa"
    if v in LEAVE:
        return v
    if v in OFF:
        return "libur"
    return v


# ═══ Masa kerja (prorata) ═════════════════════════════════════════════════════
END_DATE_FIELDS = ("resign_date", "last_working_date", "resignation_effective_date", "end_date")


def employment_window(emp: dict | None) -> tuple[date | None, date | None]:
    """(tanggal masuk, tanggal keluar) dari data karyawan. `joined_at` SENGAJA tidak dipakai: nilainya
    bawaan = waktu data dibuat di sistem, bukan tanggal masuk kerja (memakai itu = prorata palsu)."""
    e = emp or {}
    join = _d(e.get("join_date"))
    end = None
    for f in END_DATE_FIELDS:
        end = _d(e.get(f))
        if end:
            break
    return join, end


def employed_on(d: date, join: date | None, end: date | None) -> bool:
    return (join is None or d >= join) and (end is None or d <= end)


# ═══ Versi profil gaji (kenaikan berlaku mulai tanggal tertentu) ═════════════
def profile_versions(profile: dict) -> list[dict]:
    """Versi tarif terurut naik menurut `effective_from` (None = sejak awal). Profil lama tanpa
    `rate_versions` = satu versi dengan tarif profil."""
    vers = [v for v in (profile.get("rate_versions") or []) if isinstance(v, dict)]
    if not vers:
        return [{"effective_from": None, "base_rate": float(profile.get("base_rate") or 0),
                 "overtime_rate": float(profile.get("overtime_rate") or 0)}]
    return sorted(vers, key=lambda v: str(v.get("effective_from") or ""))


def version_on(profile: dict, d: date) -> dict:
    cur = None
    for v in profile_versions(profile):
        eff = _d(v.get("effective_from"))
        if eff is None or eff <= d:
            cur = v
    return cur or profile_versions(profile)[0]


def rate_on(profile: dict, d: date, field: str = "base_rate") -> float:
    return float(version_on(profile, d).get(field) or 0)


# ═══ Klasifikasi hari (potongan absen, peringatan tanpa catatan) ══════════════
def leave_kind(lv: dict, ltype: dict | None = None) -> str:
    k = str(lv.get("leave_kind") or lv.get("request_type") or (ltype or {}).get("request_type") or "cuti").lower()
    return k if k in LEAVE else "cuti"


def leave_is_paid(lv: dict, ltype: dict | None = None) -> bool:
    """Kontrak absen: `pay_decision` paid/unpaid diputuskan HR; kosong → bendera `unpaid` jenis cuti."""
    dec = str(lv.get("pay_decision") or "").lower()
    if dec in ("paid", "unpaid"):
        return dec == "paid"
    return not bool((ltype or {}).get("unpaid"))


def _leave_covers(lv: dict, d: date) -> bool:
    f, t = _d(lv.get("from_date")), _d(lv.get("to_date") or lv.get("from_date"))
    return bool(f and t and f <= d <= t)


def classify_days(work_days: list[date], events: list[dict], leaves: list[dict], leave_types: dict,
                  *, counts=None) -> dict:
    """Status gaji per hari kerja. Return {iso: {kind, weight, status, leave_request_id, no_note}}.

    kind: hadir · libur · alpa · cuti_dibayar · tidak_dibayar · tanpa_catatan.
    weight = bobot hari potongan (1; setengah hari 0,5); hanya alpa & tidak_dibayar yang dipotong.
    `counts(rec)` = attendance_policy.attendance_counts (selfie DITOLAK bukan kehadiran)."""
    counts = counts or (lambda r: True)
    by_date: dict = {}
    for ev in events or []:
        by_date.setdefault(str(ev.get("date") or "")[:10], []).append(ev)
    approved = {lv.get("id"): lv for lv in leaves or [] if lv.get("status") == "approved"}
    out: dict = {}
    for d in work_days:
        iso = d.isoformat()
        evs = by_date.get(iso) or []
        present = any(norm_status(e.get("status")) == "hadir" and counts(e) for e in evs)
        leave_ev = next((e for e in evs if norm_status(e.get("status")) in LEAVE), None)
        alpa_ev = next((e for e in evs if norm_status(e.get("status")) == "alpa"), None)
        off_ev = any(norm_status(e.get("status")) == "libur" for e in evs)
        lv_doc = None
        if leave_ev is None and not present and alpa_ev is None and not off_ev:
            # Cuti disetujui yang belum punya catatan absen harian (data lama) — aturan yang SAMA.
            lv_doc = next((lv for lv in approved.values() if _leave_covers(lv, d)), None)
        row = {"kind": "hadir", "weight": 0.0, "status": None, "leave_request_id": None, "no_note": False}
        if leave_ev is not None and not (present and not leave_ev.get("half_day")):
            req = approved.get(leave_ev.get("leave_request_id")) if leave_ev.get("leave_request_id") else None
            kind = norm_status(leave_ev.get("status"))
            half = bool(leave_ev.get("half_day") or (req or {}).get("is_half_day"))
            if req is None:
                paid = False
            elif "paid_leave" in leave_ev and leave_ev.get("paid_leave") is not None:
                paid = bool(leave_ev.get("paid_leave"))
            else:
                paid = leave_is_paid(req, leave_types.get(req.get("leave_type_id")))
            row.update(status=kind, leave_request_id=(req or {}).get("id"),
                       kind="cuti_dibayar" if paid else "tidak_dibayar",
                       weight=0.0 if paid else (0.5 if half else 1.0),
                       no_note=kind in ("izin", "sakit") and not (req or {}).get("attachment_url"))
            if kind == "cuti" and req is None:
                row["no_note"] = True
        elif lv_doc is not None:
            lt = leave_types.get(lv_doc.get("leave_type_id"))
            kind = leave_kind(lv_doc, lt)
            paid = leave_is_paid(lv_doc, lt)
            half = bool(lv_doc.get("is_half_day") or lv_doc.get("half_day"))
            row.update(status=kind, leave_request_id=lv_doc.get("id"),
                       kind="cuti_dibayar" if paid else "tidak_dibayar",
                       weight=0.0 if paid else (0.5 if half else 1.0),
                       no_note=kind in ("izin", "sakit") and not lv_doc.get("attachment_url"))
        elif present:
            row["status"] = "hadir"
        elif alpa_ev is not None:
            row.update(status="alpa", kind="alpa", weight=0.5 if alpa_ev.get("half_day") else 1.0)
        elif off_ev:
            row.update(status="libur", kind="libur")
        elif evs and all(not counts(e) for e in evs):
            # hanya catatan selfie yang ditolak HR tanpa status alpa (data lama) → alpa
            row.update(status="alpa", kind="alpa", weight=1.0)
        elif evs:
            row["status"] = norm_status(evs[0].get("status")) or "hadir"
        else:
            row.update(kind="tanpa_catatan")
        out[iso] = row
    return out


def summarize_days(classified: dict, *, until: date | None = None) -> dict:
    s = {"alpa": 0.0, "tidak_dibayar": 0.0, "cuti_dibayar": 0, "hadir": 0, "libur": 0,
         "tanpa_catatan": 0, "izin_tanpa_surat": 0, "potong_hari": 0.0}
    for iso, r in classified.items():
        k = r["kind"]
        if k == "tanpa_catatan":
            if until is None or date.fromisoformat(iso) <= until:
                s["tanpa_catatan"] += 1
            continue
        if k in ("alpa", "tidak_dibayar"):
            s[k] += r["weight"]
            s["potong_hari"] += r["weight"]
        else:
            s[k] = s.get(k, 0) + 1
        if r.get("no_note"):
            s["izin_tanpa_surat"] += 1
    return s


# ═══ Lembur per hari (PP 35/2021) ═════════════════════════════════════════════
def tier_factor(hours: float, tiers: list) -> float:
    """Faktor pengali untuk `hours` jam lembur dengan tingkatan [[sampai_jam_ke, pengali], …, [None, pengali]]."""
    h = max(0.0, float(hours or 0))
    total, prev = 0.0, 0.0
    for upto, mult in tiers:
        top = float("inf") if upto is None else float(upto)
        if h <= prev:
            break
        total += (min(h, top) - prev) * float(mult)
        prev = top
    return total


def overtime_tiers(cfg: dict, *, rest_day: bool, work_days_per_week: int) -> list:
    """Tingkatan lembur dari Pengaturan Payroll. Hari kerja: jam ke-1 × 1,5 lalu × 2. Hari istirahat /
    libur resmi (PP 35/2021 Pasal 31): 6 hari kerja → jam 1–7 × 2, jam ke-8 × 3, jam 9 dst × 4;
    5 hari kerja → jam 1–8 × 2, jam ke-9 × 3, jam 10 dst × 4."""
    if not rest_day:
        return [[1, float(cfg.get("first_hour_multiplier") or 1.5)],
                [None, float(cfg.get("next_hours_multiplier") or 2.0)]]
    first = float(cfg.get("rest_day_first_hours_5d" if work_days_per_week <= 5 else "rest_day_first_hours_6d")
                  or (8 if work_days_per_week <= 5 else 7))
    return [[first, float(cfg.get("rest_day_first_multiplier") or 2.0)],
            [first + 1, float(cfg.get("rest_day_next_hour_multiplier") or 3.0)],
            [None, float(cfg.get("rest_day_after_multiplier") or 4.0)]]


def overtime_days(events: list[dict], requests: list[dict], classified: dict, *, off_weekdays, holidays: set,
                  cfg: dict, work_days_per_week: int, counts=None) -> list[dict]:
    """Lembur per tanggal: dibayar HANYA bila ada pengajuan DISETUJUI yang menutupnya, atau HR menandai
    `overtime_paid: true` di absensi hari itu. `overtime_paid: false` eksplisit = HR memutuskan tidak dibayar.
    Pengali dari pengaturan (per hari), `rate_multiplier` pengajuan diabaikan."""
    counts = counts or (lambda r: True)
    att: dict = {}
    for ev in events or []:
        if not counts(ev):
            continue
        h = float(ev.get("overtime_hours") or 0)
        if h <= 0:
            continue
        iso = str(ev.get("date") or "")[:10]
        cur = att.setdefault(iso, {"hours": 0.0, "paid_flag": None})
        cur["hours"] += h
        if ev.get("overtime_paid") is not None:
            cur["paid_flag"] = bool(ev.get("overtime_paid"))
    req: dict = {}
    for r in requests or []:
        if r.get("status") != "approved":
            continue
        iso = str(r.get("date") or "")[:10]
        req[iso] = req.get(iso, 0.0) + max(0.0, float(r.get("hours") or 0))
    out = []
    for iso in sorted(set(att) | set(req)):
        a = att.get(iso) or {"hours": 0.0, "paid_flag": None}
        r_hours = req.get(iso, 0.0)
        day = _d(iso)
        rest = day.weekday() in off_weekdays or iso in holidays
        if (classified.get(iso) or {}).get("kind") == "alpa":
            paid, hours, src = 0.0, a["hours"] or r_hours, "hari alpa"
        elif a["paid_flag"] is False:
            paid, hours, src = 0.0, a["hours"], "ditandai HR tidak dibayar"
        elif a["paid_flag"] is True:
            paid, hours, src = a["hours"], a["hours"], "ditandai HR dibayar"
        elif r_hours > 0:
            paid = r_hours if a["hours"] <= 0 else min(a["hours"], r_hours)
            hours, src = max(a["hours"], r_hours), "pengajuan disetujui"
        else:
            paid, hours, src = 0.0, a["hours"], "tanpa pengajuan"
        tiers = overtime_tiers(cfg, rest_day=rest, work_days_per_week=work_days_per_week)
        out.append({"date": iso, "hours": round(hours, 2), "paid_hours": round(paid, 2), "basis": src,
                    "day_type": "hari istirahat/libur" if rest else "hari kerja",
                    "factor": round(tier_factor(paid, tiers), 4)})
    return out


# ═══ Bonus kehadiran: kapan hangus ════════════════════════════════════════════
def bonus_forfeit_reasons(cfg: dict, summary: dict, *, days_present: int, days_late: int, late_minutes: int) -> list:
    """Alasan bonus kehadiran hangus menurut Pengaturan Payroll (key `attendance_bonus`). [] = tetap dibayar."""
    if cfg.get("enabled") is False:
        return []
    out = []
    if days_present <= 0:
        out.append("tidak ada hari hadir")
    alpa = float(summary.get("alpa") or 0)
    if cfg.get("forfeit_if_alpa", cfg.get("require_full_attendance", True)) and alpa > float(cfg.get("max_alpa_days") or 0):
        out.append(f"{alpa:g} hari alpa")
    izin = int(summary.get("izin_tanpa_surat") or 0)
    if cfg.get("forfeit_if_izin_no_note", True) and izin > int(cfg.get("max_izin_no_note_days") or 0):
        out.append(f"{izin} hari izin/sakit tanpa surat")
    if cfg.get("forfeit_if_late", True) and days_late > int(cfg.get("max_late_days_allowed") or 0):
        out.append(f"terlambat {days_late} hari")
    lim = int(cfg.get("late_minutes_limit") or 0)
    if lim > 0 and late_minutes > lim:
        out.append(f"terlambat {late_minutes} menit (batas {lim})")
    mn = int(cfg.get("min_days_present") or 0)
    if mn > 0 and days_present < mn:
        out.append(f"hadir {days_present} hari (minimal {mn})")
    return out


def is_attendance_bonus(allowance: dict, cfg: dict) -> bool:
    ids = [str(x) for x in (cfg.get("allowance_ids") or []) if x]
    if ids:
        return str(allowance.get("allowance_id") or "") in ids
    return "kehadiran" in str(allowance.get("name") or "").lower()


# ═══ Kunci absensi (dipanggil paket absen) ════════════════════════════════════
async def attendance_lock(db, employee_id: str, day) -> dict | None:
    """Run FINAL yang mencakup tanggal ini untuk karyawan ini → {run_id, run_number}; selain itu None."""
    d = _d(day)
    if not d or not employee_id:
        return None
    iso = d.isoformat()
    # Penyatuan paket absen + payroll (6 Nov 2026): periode dibaca dari RUN (selalu ada) dan dari slip
    # (bila slip menyimpan periodenya sendiri) — satu aturan untuk HR grid, cuti, koreksi, dan payroll.
    runs = await db.rahaza_payroll_runs.find(
        {"status": "finalized", "period_from": {"$lte": iso}, "period_to": {"$gte": iso}},
        {"_id": 0, "id": 1, "run_number": 1}).to_list(50)
    for r in runs:
        if await db.rahaza_payslips.find_one({"run_id": r.get("id"), "employee_id": employee_id}, {"_id": 0, "id": 1}):
            return {"run_id": r.get("id"), "run_number": r.get("run_number")}
    slips = await db.rahaza_payslips.find(
        {"employee_id": employee_id, "period_from": {"$lte": iso}, "period_to": {"$gte": iso}},
        {"_id": 0, "run_id": 1}).to_list(50)
    run_ids = list({s.get("run_id") for s in slips if s.get("run_id")})
    if not run_ids:
        return None
    run = await db.rahaza_payroll_runs.find_one(
        {"id": {"$in": run_ids}, "status": "finalized"}, {"_id": 0, "id": 1, "run_number": 1})
    return {"run_id": run["id"], "run_number": run.get("run_number")} if run else None


async def is_attendance_locked(db, employee_id: str, day) -> bool:
    """True bila absensi karyawan pada tanggal itu sudah masuk run gaji FINAL (dibatalkan = tidak terkunci).
    Koreksi sesudah terkunci tidak mengubah run itu; run berikutnya menghitung selisihnya sebagai
    baris penyesuaian (lihat `correction_lines`)."""
    return (await attendance_lock(db, employee_id, day)) is not None


# ═══ Koreksi absensi sesudah terkunci → baris penyesuaian run berikutnya ══════
def snapshot_of(classified: dict, ot_days: list) -> dict:
    """Jejak per tanggal yang disimpan di slip: bobot potongan + faktor lembur dibayar."""
    snap = {iso: {"ded": r["weight"], "ot": 0.0} for iso, r in classified.items() if r["weight"]}
    for o in ot_days:
        if o["factor"]:
            snap.setdefault(o["date"], {"ded": 0.0, "ot": 0.0})["ot"] = o["factor"]
    return snap


def snapshot_delta(old: dict, new: dict) -> dict:
    out = {}
    for iso in sorted(set(old) | set(new)):
        o, n = old.get(iso) or {}, new.get(iso) or {}
        dd = round(float(n.get("ded") or 0) - float(o.get("ded") or 0), 4)
        do = round(float(n.get("ot") or 0) - float(o.get("ot") or 0), 4)
        if dd or do:
            out[iso] = {"ded": dd, "ot": do}
    return out


def payroll_exclusion_reason(emp: dict | None, pf: date, pt: date) -> str | None:
    """Alasan karyawan TIDAK ikut run periode pf..pt (None = ikut).

    Tahap 2: karyawan yang keluar di tengah periode TETAP ikut run periode itu (dibayar prorata) walau
    sudah dinonaktifkan; nonaktif tanpa tanggal keluar tetap dikecualikan (perilaku P5)."""
    if emp is None:
        return "data karyawan tidak ditemukan"
    join, end = employment_window(emp)
    if join and join > pt:
        return "belum mulai bekerja di periode ini"
    if end and end < pf:
        return "sudah keluar sebelum periode ini"
    if emp.get("active") is False and not (end and end >= pf):
        return "karyawan nonaktif"
    return None
