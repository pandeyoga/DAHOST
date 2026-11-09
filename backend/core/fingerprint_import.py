"""Impor data mesin sidik jari (ZKTeco/Fingerspot) — file EKSPOR mesin & sinkron langsung (2026-11-06, Tahap 2).

Keputusan owner 6 Nov 2026: mesin di kantor tidak bisa mengirim (push) lewat https dan server di internet tidak
bisa menjangkau mesin di jaringan lokal. Jalur utama = HR mengunggah file ekspor mesin (CSV/XLSX), memetakan
kolomnya, melihat pratinjau, lalu mengimpor.

Aturan gabung (dipakai unggah file DAN sinkron langsung — satu fungsi `merge_punches`):
  · cocokkan karyawan lewat `zkteco_user_id` atau `employee_code` (kolom kode/PIN di file);
  · per karyawan per HARI: ketukan pertama = jam masuk, ketukan terakhir = jam pulang (bila ada penanda
    masuk/pulang, masuk = ketukan masuk paling awal, pulang = ketukan pulang paling akhir);
  · record absensi yang sudah ada TIDAK ditimpa: jam selfie/HR tetap; hanya kolom kosong yang diisi, atau jam
    yang sebelumnya juga berasal dari mesin (bisa bergeser ke ketukan yang lebih awal/akhir);
  · status cuti/izin/sakit/alpa/libur dari HR tidak diubah (dihitung sebagai "bentrok" di pratinjau);
  · tanggal yang sudah masuk gaji final dilewati;
  · unggah ulang file yang sama tidak mengubah apa pun (idempoten).
Dulu sinkron langsung menyisipkan SETIAP ketukan sebagai dokumen baru → bentrok indeks unik (employee_id, date)
dan berhenti dengan pesan menyesatkan "gagal terhubung".
"""
from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

from fastapi import HTTPException

from core import attendance_rules as ar

log = logging.getLogger(__name__)

MAX_ROWS = 50000
DEFAULT_IN_VALUES = ("0", "i", "in", "c/in", "check in", "checkin", "masuk", "datang", "m")
DEFAULT_OUT_VALUES = ("1", "o", "out", "c/out", "check out", "checkout", "pulang", "keluar", "p")
LEAVE_LIKE = ("cuti", "izin", "sakit", "alpa", "alfa", "alpha", "libur")


# ── Membaca file ────────────────────────────────────────────────────────────
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def read_table(filename: str, data: bytes) -> list[list]:
    """Baris mentah (list of list). CSV/TXT (pemisah dideteksi) atau XLSX (sheet pertama)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise HTTPException(503, "Pembaca Excel belum terpasang di server. Simpan file sebagai CSV lalu unggah lagi.")
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001 — file rusak / bukan xlsx
            raise HTTPException(400, "File Excel tidak bisa dibaca. Pastikan formatnya .xlsx.")
        ws = wb.worksheets[0]
        rows = [list(r) for _, r in zip(range(MAX_ROWS + 1), ws.iter_rows(values_only=True))]
        wb.close()
        return rows
    if name.endswith(".xls"):
        raise HTTPException(400, "Format .xls lama belum didukung. Buka di Excel lalu simpan sebagai .xlsx atau .csv.")
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = max((",", ";", "\t", "|"), key=sample.count)
    return [row for _, row in zip(range(MAX_ROWS + 1), csv.reader(io.StringIO(text), delimiter=delim))]


def split_header(rows: list[list], header_row: int = 0) -> tuple[list[str], list[list]]:
    """Kepala kolom = baris `header_row` (0 = baris pertama yang tidak kosong)."""
    non_empty = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not non_empty:
        raise HTTPException(400, "File kosong — tidak ada baris data.")
    idx = max(0, int(header_row or 0))
    if idx >= len(non_empty):
        raise HTTPException(400, "Baris kepala kolom melebihi jumlah baris file.")
    header = [str(c or "").strip() or f"Kolom {i + 1}" for i, c in enumerate(non_empty[idx])]
    return header, non_empty[idx + 1:]


# ── Menafsirkan nilai ───────────────────────────────────────────────────────
_DT_FORMATS = {
    "dmy": ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M"),
    "mdy": ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"),
    "ymd": ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"),
}
_D_FORMATS = {"dmy": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"), "mdy": ("%m/%d/%Y",),
              "ymd": ("%Y-%m-%d", "%Y/%m/%d")}


def _excel_serial(v: float) -> datetime:
    return datetime(1899, 12, 30) + timedelta(days=float(v))


def parse_datetime(v, order: str = "dmy") -> Optional[datetime]:
    """Tanggal-jam LOKAL (naif) dari sel. Urutan tanggal bawaan hari/bulan/tahun (format Indonesia)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:
        return _excel_serial(v)
    s = re.sub(r"\s+", " ", str(v).strip())
    try:
        return datetime.fromisoformat(s.replace("T", " ")).replace(tzinfo=None)
    except ValueError:
        pass
    orders = [order] + [o for o in ("dmy", "ymd", "mdy") if o != order]
    for o in orders:
        for fmt in _DT_FORMATS[o]:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def parse_date(v, order: str = "dmy") -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:
        return _excel_serial(v).date()
    s = str(v).strip()[:10]
    orders = [order] + [o for o in ("dmy", "ymd", "mdy") if o != order]
    for o in orders:
        for fmt in _D_FORMATS[o]:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def parse_time(v) -> Optional[time]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.time().replace(microsecond=0)
    if isinstance(v, time):
        return v.replace(microsecond=0)
    if isinstance(v, (int, float)) and 0 <= float(v) < 1:
        secs = round(float(v) * 86400)
        return time(secs // 3600 % 24, secs % 3600 // 60, secs % 60)
    s = str(v).strip().upper()
    for fmt in ("%H:%M:%S", "%H:%M", "%H.%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def _norm_code(v) -> str:
    s = str(v or "").strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s.upper()


def _direction(v, in_values: Iterable[str], out_values: Iterable[str]) -> Optional[str]:
    s = str(v if v is not None else "").strip().lower()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    if not s:
        return None
    if s in {x.lower() for x in in_values}:
        return "in"
    if s in {x.lower() for x in out_values}:
        return "out"
    return None


def validate_mapping(mapping: dict, header: list[str]) -> dict:
    m = {k: (v or "").strip() for k, v in (mapping or {}).items() if isinstance(v, str)}
    if not m.get("code"):
        raise HTTPException(400, "Pilih kolom kode karyawan / PIN.")
    if not (m.get("datetime") or (m.get("date") and m.get("time"))):
        raise HTTPException(400, "Pilih kolom tanggal-jam, atau kolom tanggal DAN kolom jam.")
    missing = [v for k, v in m.items() if k in ("code", "datetime", "date", "time", "direction") and v
               and v not in header]
    if missing:
        raise HTTPException(400, f"Kolom tidak ada di file: {', '.join(missing)}. Periksa pemetaan kolom.")
    return m


def extract_punches(header: list[str], rows: list[list], mapping: dict, *, date_order: str = "dmy",
                    in_values: Iterable[str] = DEFAULT_IN_VALUES,
                    out_values: Iterable[str] = DEFAULT_OUT_VALUES) -> tuple[list[dict], int]:
    """→ ([{code, at (naif lokal), direction}], jumlah baris tidak terbaca)."""
    m = validate_mapping(mapping, header)
    col = {name: i for i, name in enumerate(header)}

    def cell(row, key):
        name = m.get(key)
        if not name:
            return None
        i = col[name]
        return row[i] if i < len(row) else None

    out, bad = [], 0
    for row in rows:
        code = _norm_code(cell(row, "code"))
        if m.get("datetime"):
            at = parse_datetime(cell(row, "datetime"), date_order)
        else:
            d, t = parse_date(cell(row, "date"), date_order), parse_time(cell(row, "time"))
            at = datetime.combine(d, t) if d and t else None
        if not code or not at:
            bad += 1
            continue
        out.append({"code": code, "at": at.replace(microsecond=0),
                    "direction": _direction(cell(row, "direction"), in_values, out_values)
                    if m.get("direction") else None})
    return out, bad


# ── Menggabungkan ───────────────────────────────────────────────────────────
async def employee_lookup(db) -> dict:
    """{kode/PIN dinormalisasi: karyawan}. `zkteco_user_id` diutamakan di atas `employee_code`."""
    emps = await db.rahaza_employees.find({}, {"_id": 0, "id": 1, "name": 1, "employee_code": 1,
                                               "zkteco_user_id": 1, "shift_id": 1}).to_list(5000)
    by_code: dict = {}
    for e in emps:
        for key in (e.get("employee_code"),):
            k = _norm_code(key)
            if k:
                by_code.setdefault(k, e)
                if k.isdigit():
                    by_code.setdefault(k.lstrip("0") or "0", e)
    for e in emps:   # PIN mesin menang bila bentrok dengan kode karyawan lain
        k = _norm_code(e.get("zkteco_user_id"))
        if k:
            by_code[k] = e
            if k.isdigit():
                by_code[k.lstrip("0") or "0"] = e
    return by_code


def _match(code: str, lookup: dict) -> Optional[dict]:
    return lookup.get(code) or (lookup.get(code.lstrip("0") or "0") if code.isdigit() else None)


def group_days(punches: list[dict], lookup: dict) -> tuple[dict, set]:
    """{(employee_id, tanggal): {"emp", "in", "out", "count", "times"}}, kode yang tidak cocok."""
    days: dict = {}
    unmatched: set = set()
    # Penanda masuk/pulang hanya dipakai bila file/mesin benar-benar memuat KEDUANYA (banyak mesin mengirim
    # punch=0 untuk semua ketukan) — selain itu: ketukan pertama = masuk, terakhir = pulang.
    dirs = {p.get("direction") for p in punches}
    if not {"in", "out"} <= dirs:
        punches = [{**p, "direction": None} for p in punches]
    for p in sorted(punches, key=lambda x: x["at"]):
        emp = _match(p["code"], lookup)
        if not emp:
            unmatched.add(p["code"])
            continue
        day = p["at"].date().isoformat()
        # Ketukan PULANG dini hari tanpa ketukan masuk hari itu → milik shift kemarin (lewat tengah malam).
        if p.get("direction") == "out" and p["at"].hour < 12:
            prev = (p["at"].date() - timedelta(days=1)).isoformat()
            cur = days.get((emp["id"], day))
            pv = days.get((emp["id"], prev))
            if not (cur and cur.get("in")) and pv and pv.get("in") and (not pv.get("out") or pv["out"] < p["at"]):
                day = prev
        g = days.setdefault((emp["id"], day), {"emp": emp, "in": None, "out": None, "count": 0, "times": [],
                                               "directional": False})
        g["count"] += 1
        g["times"].append(p["at"])
        if p.get("direction"):
            g["directional"] = True
        if p.get("direction") == "in":
            g["in"] = g["in"] or p["at"]
        elif p.get("direction") == "out":
            g["out"] = p["at"]
    for g in days.values():
        if not g["directional"]:
            g["in"] = g["times"][0]
            g["out"] = g["times"][-1] if len(g["times"]) > 1 else None
        elif not g["in"] and g["out"] and len(g["times"]) > 1 and g["times"][0] < g["out"]:
            g["in"] = g["times"][0]
    return days, unmatched


def _to_utc(local_naive: Optional[datetime], utc_offset_hours: float) -> Optional[datetime]:
    if not local_naive:
        return None
    return (local_naive - timedelta(hours=utc_offset_hours)).replace(tzinfo=timezone.utc)


def _hours(cin, cout) -> float:
    a, b = ar._aware(cin), ar._aware(cout)
    if not a or not b:
        return 0.0
    return round(max(0.0, (b - a).total_seconds() / 3600), 2)


async def merge_punches(db, punches: list[dict], *, user: dict, apply: bool, source_label: str,
                        import_id: Optional[str] = None, utc_offset_hours: float = 7.0,
                        lookup: Optional[dict] = None) -> dict:
    """Gabungkan ketukan ke `rahaza_attendance_events`. `apply=False` = pratinjau (tidak menulis)."""
    lookup = lookup if lookup is not None else await employee_lookup(db)
    days, unmatched = group_days(punches, lookup)
    stats = {"punches": len(punches), "days": len(days), "employees": len({k[0] for k in days}),
             "new": 0, "updated": 0, "unchanged": 0, "conflict": 0, "locked": 0,
             "unmatched_codes": sorted(unmatched)[:50], "unmatched_count": len(unmatched), "samples": []}
    now = datetime.now(timezone.utc)
    from utils.employee_identity import compute_late_minutes
    for (emp_id, day), g in sorted(days.items(), key=lambda kv: (kv[0][1], kv[1]["emp"].get("employee_code") or "")):
        cin, cout = _to_utc(g["in"], utc_offset_hours), _to_utc(g["out"], utc_offset_hours)
        fp = {"import_id": import_id, "source": source_label, "punches": g["count"],
              "first": cin.isoformat() if cin else None, "last": cout.isoformat() if cout else None}
        if await ar.attendance_lock(db, emp_id, day):
            stats["locked"] += 1
            continue
        existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": day}, {"_id": 0})
        if not existing:
            stats["new"] += 1
            if len(stats["samples"]) < 20:
                stats["samples"].append({"employee": g["emp"].get("name"), "date": day, "action": "baru",
                                         "clock_in": fp["first"], "clock_out": fp["last"]})
            if apply:
                late = await compute_late_minutes(db, g["emp"], cin) if cin else {}
                if cout:   # 2026-11-09 (Q3): pulang cepat dicatat
                    late = {**late, **await ar.early_leave_fields(db, g["emp"], {"status": "hadir", "date": day}, cout)}
                hours = _hours(cin, cout)
                doc = {"id": str(uuid.uuid4()), "employee_id": emp_id, "date": day,
                       "clock_in": cin, "clock_out": cout, "hours_worked": hours, "net_hours_worked": hours,
                       "overtime_hours": 0, **late, "status": "hadir",
                       "clock_in_source": "fingerprint" if cin else None,
                       "clock_out_source": "fingerprint" if cout else None,
                       "attendance_method": "device_zkteco", "geo_status": "not_verified",
                       "face_match_status": "biometric_verified", "approval_status": "auto_approved",
                       "source": "device_zkteco", "fingerprint": fp, "notes": f"Mesin sidik jari ({source_label})",
                       "created_by": user.get("id"), "created_by_name": user.get("name", ""), "created_at": now,
                       "updated_by": user.get("id"), "updated_by_name": user.get("name", ""), "updated_at": now}
                await db.rahaza_attendance_events.insert_one(doc)
            continue

        upd: dict = {}
        ex_in, ex_out = ar._aware(existing.get("clock_in")), ar._aware(existing.get("clock_out"))
        in_from_fp = existing.get("clock_in_source") == "fingerprint"
        out_from_fp = existing.get("clock_out_source") == "fingerprint"
        if cin and (not ex_in or (in_from_fp and cin < ex_in)):
            upd["clock_in"], upd["clock_in_source"] = cin, "fingerprint"
        if cout and (not ex_out or (out_from_fp and cout > ex_out)):
            if (upd.get("clock_in") or ex_in) and cout > (upd.get("clock_in") or ex_in):
                upd["clock_out"], upd["clock_out_source"] = cout, "fingerprint"
        status = ar.normalize_status(existing.get("status"), "")
        conflict = status in LEAVE_LIKE and not existing.get("half_day")
        if conflict:
            stats["conflict"] += 1
        if not upd and (existing.get("fingerprint") or {}).get("punches") == fp["punches"]:
            stats["unchanged"] += 1
            continue
        if not upd:
            # Hanya catatan ketukan yang berubah (jam selfie/HR tetap dipakai).
            if apply:
                await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": {"fingerprint": fp}})
            stats["unchanged"] += 1
            continue
        stats["updated"] += 1
        if len(stats["samples"]) < 20:
            stats["samples"].append({"employee": g["emp"].get("name"), "date": day, "action": "dilengkapi",
                                     "clock_in": (upd.get("clock_in") or ex_in).isoformat() if (upd.get("clock_in") or ex_in) else None,
                                     "clock_out": (upd.get("clock_out") or ex_out).isoformat() if (upd.get("clock_out") or ex_out) else None})
        if not apply:
            continue
        new_in, new_out = upd.get("clock_in") or ex_in, upd.get("clock_out") or ex_out
        upd["fingerprint"] = fp
        if new_in and new_out:
            upd["hours_worked"] = _hours(new_in, new_out)
            from routes.rahaza_attendance_sessions import recompute_session_totals
            upd.update(recompute_session_totals({**existing, "hours_worked": upd["hours_worked"]}))
        if not status:
            upd["status"] = "hadir"
        if "clock_in" in upd and (upd.get("status") or status) == "hadir":
            upd.update(await compute_late_minutes(db, g["emp"], new_in, existing.get("shift_id")))
        if "clock_out" in upd:   # 2026-11-09 (Q3): pulang cepat dicatat
            upd.update(await ar.early_leave_fields(db, g["emp"], {**existing, **upd}, new_out))
        upd.update({"updated_by": user.get("id"), "updated_by_name": user.get("name", ""), "updated_at": now})
        await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": upd})
        await ar.write_attendance_audit(db, before=existing, after={**existing, **upd}, user=user,
                                        source="impor_mesin", note=source_label)
    return stats
