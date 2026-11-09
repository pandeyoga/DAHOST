"""Aturan HARI absensi — satu tempat (2026-11-06, Tahap 2 paket absen).

Isi modul ini dipakai semua jalur absen (selfie, biometrik, HR manual, grid HR, impor mesin sidik jari,
cuti) supaya aturannya tidak disalin-salin:

* `normalize_status`      — status absensi kanonik. Kontrak dengan payroll: hadir · izin · sakit · cuti ·
                             alpa · libur. Data lama `alfa`/`alpha` tetap terbaca (dibaca sebagai alpa).
* `resolve_day_shift`     — shift yang BERLAKU untuk satu karyawan pada satu tanggal:
                             shift yang dipilih HR di record hari itu → Jadwal Shift yang sudah diterbitkan
                             (menu Shift › Jadwal Shift) → penugasan shift (Shift › Kelola Shift) → shift
                             bawaan karyawan. Dulu keterlambatan selalu memakai shift bawaan karyawan.
* `find_clock_out_record` — record yang ditutup saat absen pulang. Absen pulang lewat tengah malam menutup
                             record KEMARIN bila shift-nya melewati tengah malam atau masih dalam jendela
                             (bawaan 6 jam) sesudah jam pulang shift. Dulu selalu mencari record hari ini.
* `attendance_lock`       — tanggal yang sudah masuk run gaji FINAL tidak boleh diubah HR; koreksinya lewat
                             pengajuan koreksi dan dibayar sebagai penyesuaian di run berikutnya.
* `write_attendance_audit`— jejak perubahan absensi oleh HR (siapa, kapan, sebelum → sesudah).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from utils.waktu import WIB

log = logging.getLogger(__name__)

# ── Status ──────────────────────────────────────────────────────────────────
ATTENDANCE_STATUSES = ("hadir", "izin", "sakit", "cuti", "alpa", "libur")
LEAVE_STATUSES = ("cuti", "izin", "sakit")
ABSENT_ALIASES = ("alpa", "alfa", "alpha", "absent", "absen")
STATUS_LABELS = {"hadir": "Hadir", "izin": "Izin", "sakit": "Sakit", "cuti": "Cuti", "alpa": "Alpa",
                 "libur": "Libur"}

DEFAULT_CLOCK_OUT_WINDOW_HOURS = 6
# Shift tidak diketahui → anggap hari kerja 8 jam sejak jam masuk (dipakai jendela absen pulang).
FALLBACK_SHIFT_HOURS = 8


def normalize_status(value, default: str = "hadir") -> str:
    """Status kanonik kontrak payroll. `alfa`/`alpha` (data lama) → `alpa`; kosong → `default`."""
    s = str(value or "").strip().lower()
    if not s:
        return default
    if s in ABSENT_ALIASES:
        return "alpa"
    if s in ("present",):
        return "hadir"
    return s


def is_absent(value) -> bool:
    return str(value or "").strip().lower() in ABSENT_ALIASES


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _hhmm(txt) -> Optional[time]:
    s = str(txt or "").strip()
    if ":" not in s:
        return None
    try:
        hh, mm = (int(x) for x in s.split(":")[:2])
        return time(hh % 24, mm % 60)
    except ValueError:
        return None


# ── Shift per hari ──────────────────────────────────────────────────────────
async def _shift_doc(db, shift_id) -> Optional[dict]:
    if shift_id in (None, ""):
        return None
    ids = [shift_id]
    if isinstance(shift_id, str) and shift_id.isdigit():
        ids.append(int(shift_id))
    elif isinstance(shift_id, int):
        ids.append(str(shift_id))
    return await db.rahaza_shifts.find_one({"id": {"$in": ids}}, {"_id": 0})


def _grace_of(doc: dict):
    """Toleransi terlambat sebuah shift/entri jadwal: `toleransi_menit` (isian per shift, Q4 9 Nov 2026) →
    `grace_minutes` (data lama) → None (= bawaan global `DEFAULT_GRACE_MINUTES`). Nilai 0 sah (tanpa toleransi)."""
    for k in ("toleransi_menit", "grace_minutes"):
        v = (doc or {}).get(k)
        if v not in (None, ""):
            try:
                return max(0, int(float(v)))
            except (TypeError, ValueError):
                continue
    return None


def _shape(start, end, *, grace=None, code=None, name=None, source: str, overnight=None,
           break_minutes=None, break_start=None) -> Optional[dict]:
    st, en = _hhmm(start), _hhmm(end)
    if not st:
        return None
    bs = _hhmm(break_start)
    from utils.employee_identity import DEFAULT_GRACE_MINUTES
    try:
        brk = max(0, int(float(break_minutes or 0)))
    except (TypeError, ValueError):
        brk = 0
    return {
        "start_time": st.strftime("%H:%M"),
        "end_time": en.strftime("%H:%M") if en else None,
        "grace_minutes": int(grace if grace not in (None, "") else DEFAULT_GRACE_MINUTES),
        # 2026-11-09 (Q5): lama & jam mulai istirahat — acuan cuti setengah hari
        # (utils.employee_identity.half_day_points; `istirahat_mulai` diisi di master shift oleh agen SHIFT)
        "break_minutes": brk,
        "break_start": bs.strftime("%H:%M") if bs else None,
        "code": code, "name": name, "source": source,
        "overnight": bool(overnight) if overnight is not None else bool(en and en <= st),
    }


def _from_shift(doc: dict, source: str) -> Optional[dict]:
    if not doc:
        return None
    return _shape(doc.get("start_time") or doc.get("check_in_time"),
                  doc.get("end_time") or doc.get("check_out_time"),
                  grace=_grace_of(doc), code=doc.get("code") or doc.get("shift_code"),
                  name=doc.get("name") or doc.get("shift_name"), source=source,
                  overnight=doc.get("is_overnight") if doc.get("is_overnight") else None,
                  break_minutes=doc.get("break_duration_minutes", doc.get("break_minutes")),
                  break_start=doc.get("istirahat_mulai") or doc.get("break_start"))


async def published_schedule_entry(db, emp_id: Optional[str], day) -> Optional[dict]:
    """Entri Jadwal Shift TERBIT (terbit paling baru menang) untuk karyawan pada `day`; None = tidak dijadwalkan.
    Entri `libur: true` (pola/roster agen SHIFT) = hari libur menurut jadwal."""
    if not emp_id:
        return None
    day = str(day)[:10]
    scheds = await db.rahaza_schedules.find(
        {"status": "published", "start_date": {"$lte": day}, "end_date": {"$gte": day}},
        {"_id": 0, "shifts": 1, "published_at": 1}).sort("published_at", -1).to_list(20)
    for sc in scheds:
        for e in sc.get("shifts") or []:
            if e.get("employee_id") == emp_id and str(e.get("date") or "")[:10] == day:
                return e
    return None


async def scheduled_day_off(db, emp: Optional[dict], day) -> bool:
    """True bila Jadwal Shift terbit menandai karyawan LIBUR pada `day` (terlambat/pulang cepat = 0)."""
    e = await published_schedule_entry(db, (emp or {}).get("id"), day)
    return bool(e and e.get("libur"))


async def _shift_from_entry(db, e: dict) -> Optional[dict]:
    """Shift satu entri jadwal: master shift lewat `shift_id` LEBIH DULU (toleransi, istirahat, jam terbaru), lalu jam
    yang tersalin di entri (jadwal lama tanpa id). 2026-11-09 (permintaan agen SHIFT)."""
    if e.get("shift_id") not in (None, ""):
        master = _from_shift(await _shift_doc(db, e.get("shift_id")), "jadwal")
        if master:
            if _grace_of(e) is not None:
                master["grace_minutes"] = _grace_of(e)
            return master
    return _shape(e.get("start_time"), e.get("end_time"), grace=_grace_of(e),
                  code=e.get("shift_code"), name=e.get("shift_name"), source="jadwal",
                  overnight=e.get("is_overnight") if e.get("is_overnight") else None,
                  break_minutes=e.get("break_duration_minutes", e.get("break_minutes")),
                  break_start=e.get("istirahat_mulai") or e.get("break_start"))


async def resolve_day_shift(db, emp: Optional[dict], day, explicit_shift_id=None) -> Optional[dict]:
    """Shift yang berlaku untuk karyawan pada `day` (lihat urutan di docstring modul). None = tidak diketahui
    ATAU libur menurut Jadwal Shift terbit (entri `libur: true` — penugasan/shift bawaan tidak dipakai)."""
    day = str(day)[:10]
    if explicit_shift_id:
        sh = _from_shift(await _shift_doc(db, explicit_shift_id), "absensi")
        if sh:
            return sh
    emp = emp or {}
    emp_id = emp.get("id")
    if emp_id:
        # Jadwal Shift yang SUDAH diterbitkan (draft belum berlaku).
        e = await published_schedule_entry(db, emp_id, day)
        if e is not None:
            if e.get("libur"):
                return None
            sh = await _shift_from_entry(db, e)
            if sh:
                return sh
        assign = await db.hr_shift_assignments.find_one({
            "employee_id": emp_id, "status": "active", "effective_from": {"$lte": day},
            "$or": [{"effective_until": None}, {"effective_until": ""}, {"effective_until": {"$gte": day}}],
        }, {"_id": 0})
        if assign:
            sh = _from_shift(await _shift_doc(db, assign.get("shift_id")), "penugasan")
            if sh:
                return sh
    if emp.get("shift_id"):
        return _from_shift(await _shift_doc(db, emp.get("shift_id")), "karyawan")
    return None


async def default_shift_ids(db, emps: list, day, shifts: list, off_out: Optional[set] = None) -> dict:
    """{employee_id: shift_id} — shift bawaan grid absensi HR untuk `day` (2026-11-07, Tahap 5).

    Urutan SAMA dengan `resolve_day_shift` (tanpa record hari itu): Jadwal Shift terbit → penugasan shift →
    shift bawaan karyawan. Versi massal (3 kueri untuk semua karyawan) supaya grid tidak memanggil
    `resolve_day_shift` per baris. Hanya shift AKTIF di `shifts` yang dikembalikan; jadwal (yang menyimpan
    kode shift) dipetakan ke id lewat kode. Karyawan tanpa shift yang diketahui tidak ada di hasil — grid
    memakai shift pertama seperti sebelumnya. Dulu grid SELALU memakai shift pertama untuk semua karyawan."""
    day = str(day)[:10]
    by_id = {str(s.get("id")): s for s in shifts or [] if s.get("id") is not None}
    by_code = {str(s.get("code") or "").upper(): s for s in shifts or [] if s.get("code")}
    emp_ids = [e.get("id") for e in emps or [] if e.get("id")]
    out: dict = {}
    if not emp_ids:
        return out

    def _ok(sid):
        return str(sid) if sid is not None and str(sid) in by_id else None

    scheds = await db.rahaza_schedules.find(
        {"status": "published", "start_date": {"$lte": day}, "end_date": {"$gte": day}},
        {"_id": 0, "shifts": 1, "published_at": 1}).sort("published_at", -1).to_list(20)
    off: set = set()
    for sc in scheds:   # terbit paling baru menang (sama dengan resolve_day_shift)
        for e in sc.get("shifts") or []:
            eid = e.get("employee_id")
            if eid in out or eid in off or str(e.get("date") or "")[:10] != day:
                continue
            if e.get("libur"):   # 2026-11-09: libur menurut jadwal → tanpa shift bawaan (tidak jatuh ke penugasan)
                off.add(eid)
                continue
            # 2026-11-09: `shift_id` entri lebih dulu, kode untuk jadwal lama
            sh = by_id.get(str(e.get("shift_id"))) if e.get("shift_id") not in (None, "") else None
            sh = sh or by_code.get(str(e.get("shift_code") or "").upper())
            if sh:
                out[eid] = str(sh["id"])
    if off_out is not None:
        off_out |= off
    rest = [i for i in emp_ids if i not in out and i not in off]
    if rest:
        async for a in db.hr_shift_assignments.find({
            "employee_id": {"$in": rest}, "status": "active", "effective_from": {"$lte": day},
            "$or": [{"effective_until": None}, {"effective_until": ""}, {"effective_until": {"$gte": day}}],
        }, {"_id": 0, "employee_id": 1, "shift_id": 1}):
            sid = _ok(a.get("shift_id"))
            if sid and a.get("employee_id") not in out:
                out[a["employee_id"]] = sid
    for e in emps or []:
        if e.get("id") and e["id"] not in out and e["id"] not in off:
            sid = _ok(e.get("shift_id"))
            if sid:
                out[e["id"]] = sid
    return out


def shift_end_utc(day, shift: Optional[dict], clock_in=None) -> Optional[datetime]:
    """Instan jam pulang shift untuk tanggal kerja `day` (shift lewat tengah malam → besoknya)."""
    d = date.fromisoformat(str(day)[:10])
    if shift and shift.get("end_time"):
        en = _hhmm(shift["end_time"])
        end = datetime.combine(d, en, tzinfo=WIB)
        if shift.get("overnight"):
            end += timedelta(days=1)
        return end.astimezone(timezone.utc)
    cin = _aware(clock_in)
    return cin + timedelta(hours=FALLBACK_SHIFT_HOURS) if cin else None


# ── Terlambat & pulang cepat satu catatan (2026-11-09, H5/Q3/M13) ───────────
def counts_timing(rec: Optional[dict]) -> bool:
    """Catatan yang punya jam kerja untuk dinilai terlambat/pulang cepat: hadir, atau cuti/izin/sakit SETENGAH hari."""
    r = rec or {}
    st = normalize_status(r.get("status"), "hadir")
    return st == "hadir" or (st in LEAVE_STATUSES and bool(r.get("half_day")))


async def early_leave_fields(db, emp: dict, rec: dict, clock_out=None) -> dict:
    """{early_leave_minutes, shift_end, early_leave_reason} untuk absen pulang catatan `rec` (Q3: dicatat saja)."""
    from utils.employee_identity import compute_early_leave_minutes
    cout = clock_out if clock_out is not None else rec.get("clock_out")
    return await compute_early_leave_minutes(db, emp, cout if counts_timing(rec) else None,
                                             rec.get("date"), rec.get("shift_id"))


async def timing_fields(db, emp: dict, rec: dict) -> dict:
    """Menit terlambat + pulang cepat dihitung ULANG dari jam masuk/pulang & shift catatan (dipakai tombol
    "Hitung ulang terlambat", persetujuan/pembatalan cuti, dan tugas luar)."""
    from utils.employee_identity import compute_late_minutes
    out = await compute_late_minutes(db, emp, _aware(rec.get("clock_in")) if counts_timing(rec) else None,
                                     rec.get("shift_id"))
    out.update(await early_leave_fields(db, emp, rec))
    return out


TIMING_KEYS = ("late_minutes", "is_late", "late_reason", "early_leave_minutes", "early_leave_reason")


# ── Absen pulang (termasuk lewat tengah malam) ──────────────────────────────
async def clock_out_window_hours(db) -> float:
    doc = await db.rahaza_office_locations.find_one({"is_primary": True}, {"_id": 0}) or {}
    try:
        v = float(doc.get("clock_out_window_hours"))
    except (TypeError, ValueError):
        return float(DEFAULT_CLOCK_OUT_WINDOW_HOURS)
    return max(0.0, min(v, 24.0))


async def previous_day_open_record(db, emp: dict, now: Optional[datetime] = None) -> Optional[dict]:
    """Record KEMARIN yang belum absen pulang dan masih boleh ditutup sekarang (lihat docstring modul)."""
    now = _aware(now) or _now()
    prev = (now.astimezone(WIB).date() - timedelta(days=1)).isoformat()
    rec = await db.rahaza_attendance_events.find_one({"employee_id": emp["id"], "date": prev}, {"_id": 0})
    if not rec or not rec.get("clock_in") or rec.get("clock_out"):
        return None
    shift = await resolve_day_shift(db, emp, prev, rec.get("shift_id"))
    end = shift_end_utc(prev, shift, rec.get("clock_in"))
    if not end:
        return None
    window = timedelta(hours=await clock_out_window_hours(db))
    return rec if now <= end + window else None


async def find_clock_out_record(db, emp: dict, now: Optional[datetime] = None) -> tuple[Optional[dict], str]:
    """(record yang ditutup, alasan bila tidak ada). Hari ini lebih dulu; lalu record kemarin (lewat tengah malam)."""
    now = _aware(now) or _now()
    today = now.astimezone(WIB).date().isoformat()
    rec = await db.rahaza_attendance_events.find_one({"employee_id": emp["id"], "date": today}, {"_id": 0})
    if rec and rec.get("clock_in") and not rec.get("clock_out"):
        return rec, ""
    if not (rec and rec.get("clock_in")):
        prev = await previous_day_open_record(db, emp, now)
        if prev:
            return prev, ""
    if rec and rec.get("clock_out"):
        return None, "Sudah clock-out hari ini."
    return None, "Belum clock-in hari ini."


# ── Kunci payroll ───────────────────────────────────────────────────────────
async def _local_lock(db, employee_id: str, day: str) -> Optional[dict]:
    """Cadangan bila helper payroll belum ada: run FINAL yang mencakup tanggal & memuat karyawan itu."""
    runs = await db.rahaza_payroll_runs.find(
        {"status": "finalized", "period_from": {"$lte": day}, "period_to": {"$gte": day}},
        {"_id": 0, "id": 1, "run_number": 1}).to_list(20)
    for r in runs:
        if await db.rahaza_payslips.find_one({"run_id": r.get("id"), "employee_id": employee_id}, {"_id": 0, "id": 1}):
            return {"run_id": r.get("id"), "run_number": r.get("run_number")}
    return None


async def attendance_lock(db, employee_id: str, day) -> Optional[dict]:
    """None bila boleh diubah; dict {run_id, run_number} bila tanggal sudah masuk penggajian final."""
    if not employee_id or not day:
        return None
    day = str(day)[:10]
    helper = None
    try:  # helper resmi payroll (mengembalikan {run_id, run_number}) — impor malas
        from routes.rahaza_payroll_shared import attendance_lock as helper  # type: ignore
    except ImportError:
        helper = None
    if helper is not None:
        res = helper(db, employee_id, day)
        if hasattr(res, "__await__"):
            res = await res
        if not res:
            return None
        return dict(res) if isinstance(res, dict) else {"run_id": None, "run_number": None}
    return await _local_lock(db, employee_id, day)


def lock_message(day, lock: dict, who: str = "") -> str:
    run_txt = f" ({lock.get('run_number')})" if lock.get("run_number") else ""
    pre = f"Absensi {who} tanggal {day}" if who else f"Absensi tanggal {day}"
    return (f"{pre} sudah masuk penggajian final{run_txt} sehingga tidak bisa diubah lagi. "
            "Ajukan koreksi absen; selisihnya dibayar sebagai penyesuaian di penggajian berikutnya.")


async def ensure_not_locked(db, employee_id: str, day, who: str = "") -> None:
    lock = await attendance_lock(db, employee_id, day)
    if lock:
        raise HTTPException(409, lock_message(str(day)[:10], lock, who))


# ── Jejak perubahan oleh HR ─────────────────────────────────────────────────
AUDIT_FIELDS = ("status", "clock_in", "clock_out", "hours_worked", "overtime_hours", "overtime_paid",
                "shift_id", "notes", "late_minutes", "early_leave_minutes", "leave_request_id", "half_day",
                "paid_leave", "approval_status", "tugas_luar")


def _plain(v):
    if isinstance(v, datetime):
        return _aware(v).isoformat()
    return v


def audit_diff(before: Optional[dict], after: dict) -> tuple[dict, dict]:
    b, a = {}, {}
    before = before or {}
    for k in AUDIT_FIELDS:
        if k not in after:
            continue
        old, new = _plain(before.get(k)), _plain(after.get(k))
        if old != new:
            b[k], a[k] = old, new
    return b, a


async def write_attendance_audit(db, *, before: Optional[dict], after: dict, user: dict, source: str,
                                 employee_id: str = "", day: str = "", event_id: str = "",
                                 note: str = "") -> Optional[dict]:
    """Simpan satu baris jejak bila ada kolom yang berubah. `source`: grid · manual · persetujuan_selfie ·
    lembur_dibayar · koreksi · cuti · batal_cuti · impor_mesin."""
    b, a = audit_diff(before, after)
    if not a:
        return None
    doc = {
        "id": str(uuid.uuid4()),
        "event_id": event_id or (before or {}).get("id") or after.get("id"),
        "employee_id": employee_id or (before or {}).get("employee_id") or after.get("employee_id"),
        "date": str(day or (before or {}).get("date") or after.get("date") or "")[:10],
        "source": source, "before": b, "after": a, "note": note or "",
        "changed_by": (user or {}).get("id"), "changed_by_name": (user or {}).get("name", ""),
        "changed_at": _now(),
    }
    await db.rahaza_attendance_audit.insert_one(dict(doc))
    return doc
