"""Rekap absensi & PENGECUALIAN — aturan deterministik (audit HR Tahap D, 9 Nov 2026).

Dipakai Asisten AI (alat `rekap_absensi_pengecualian`, AI hanya merangkum) lewat
`GET /api/hr/absensi/pengecualian`. Per karyawan aktif per hari dalam periode (paling lama 62 hari, sampai hari ini),
catatan absen dicocokkan dengan: cuti/izin/sakit DISETUJUI (termasuk setengah hari), dinas/tugas luar yang disetujui,
kalender libur SDM + libur mingguan, dan shift yang berlaku (jadwal terbit → penugasan → shift utama,
`core.shift_roster`). Tidak ada yang ditulis.

Kategori (tingkat: perlu_tindakan · periksa · info):
  lupa_absen_pulang          absen masuk tanpa absen pulang (hari sudah lewat)   → saran koreksi jam pulang = jam
                             pulang shift
  tanpa_catatan_dinas        hari kerja tanpa catatan padahal dinas disetujui    → saran koreksi status hadir
  alpa_padahal_dinas         alpa padahal dinas disetujui                         → saran koreksi status hadir
  terlambat_hari_libur       menit terlambat di hari libur/bukan hari kerja      → saran hitung ulang (jam masuk sama)
  terlambat_cuti_setengah    terlambat pada hari cuti setengah hari pagi         → saran hitung ulang (jam masuk sama)
  alpa_padahal_cuti          alpa padahal cuti/izin/sakit disetujui              → periksa (perbaiki lewat pengajuan cuti)
  absen_di_hari_cuti         hadir/absen masuk pada hari cuti penuh disetujui    → periksa
  lembur_tanpa_pengajuan     jam lembur tercatat tanpa pengajuan disetujui       → periksa (tandai dibayar di Absensi)
  lembur_tanpa_absen         pengajuan lembur disetujui tanpa absen hari itu      → periksa
  terlambat                  terlambat biasa (hari kerja)                         → info
  alpa                       alpa tercatat                                        → info
  tanpa_catatan              hari kerja tanpa catatan absen (tidak dipotong gaji — keputusan owner) → info
Saran koreksi memakai jalur koreksi absen yang ada (`POST /api/rahaza/attendance/corrections` lalu `/approve`):
tanggal yang sudah masuk gaji final otomatis menjadi penyesuaian di penggajian berikutnya.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from core import shift_roster as sr
from utils.waktu import WIB

KATEGORI = {
    "lupa_absen_pulang": ("Lupa absen pulang", "perlu_tindakan"),
    "tanpa_catatan_dinas": ("Tanpa catatan padahal dinas", "perlu_tindakan"),
    "alpa_padahal_dinas": ("Alpa padahal dinas", "perlu_tindakan"),
    "terlambat_hari_libur": ("Terlambat di hari libur", "perlu_tindakan"),
    "terlambat_cuti_setengah": ("Terlambat pada cuti setengah hari", "perlu_tindakan"),
    "alpa_padahal_cuti": ("Alpa padahal cuti disetujui", "periksa"),
    "absen_di_hari_cuti": ("Absen di hari cuti", "periksa"),
    "lembur_tanpa_pengajuan": ("Lembur tanpa pengajuan", "periksa"),
    "lembur_tanpa_absen": ("Pengajuan lembur tanpa absen", "periksa"),
    "terlambat": ("Terlambat", "info"),
    "alpa": ("Alpa", "info"),
    "tanpa_catatan": ("Hari kerja tanpa catatan absen", "info"),
}
TINGKAT = ("perlu_tindakan", "periksa", "info")
STATUS_DINAS = ("approved", "advance_paid", "on_trip", "completed")
MAKS_BARIS = 2000


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


def jam_lokal(v) -> Optional[str]:
    d = _aware(v)
    return d.astimezone(WIB).strftime("%H:%M") if d else None


def _status(v) -> str:
    from core.attendance_rules import normalize_status
    return normalize_status(v)


async def _dinas(db, emps: list, dari: str, sampai: str) -> set:
    """{(employee_id, iso)} dinas/tugas luar disetujui. Pengajuan dinas menyimpan ID AKUN di `employee_id`
    (`routes/employee_travel_requests.py`) → dipetakan ke karyawan lewat `user_id` karyawan / `users.employee_id`."""
    akun_ke_emp = {e.get("user_id"): e["id"] for e in emps if e.get("user_id")}
    ids = [e["id"] for e in emps]
    async for u in db.users.find({"employee_id": {"$in": ids}}, {"_id": 0, "id": 1, "employee_id": 1}):
        if u.get("id"):
            akun_ke_emp.setdefault(u["id"], u.get("employee_id"))
    out = set()
    rows = await db.employee_travel_requests.find(
        {"status": {"$in": list(STATUS_DINAS)}, "start_date": {"$lte": sampai}, "end_date": {"$gte": dari}},
        {"_id": 0, "employee_id": 1, "start_date": 1, "end_date": 1}).to_list(2000)
    for r in rows:
        eid = akun_ke_emp.get(r.get("employee_id")) or (r.get("employee_id") if r.get("employee_id") in ids else None)
        if not eid:
            continue
        for iso in sr.rentang(max(dari, str(r["start_date"])[:10]), min(sampai, str(r.get("end_date") or r["start_date"])[:10]),
                              maks=400):
            out.add((eid, iso))
    return out


async def rekap(db, *, dari, sampai, today: date, departemen: Optional[str] = None,
                employee_ids: Optional[list] = None) -> dict:
    a = sr.tgl(dari)
    b = min(sr.tgl(sampai), today)
    if b < a:
        raise sr.GalatRoster(400, "Periode belum dimulai (tanggal mulai sesudah hari ini).")
    tanggal = sr.rentang(a, b)
    emps = await sr.karyawan_lingkup(db, departemen=departemen or None, employee_ids=employee_ids)
    ids = [e["id"] for e in emps]
    shifts = await sr.muat_shift(db)
    sel = await sr.sel_berlaku(db, emps, tanggal, shifts)
    kunci = await sr.kunci_hari(db, ids, tanggal)
    dinas = await _dinas(db, emps, tanggal[0], tanggal[-1])
    ev: dict = {}
    for r in await db.rahaza_attendance_events.find(
            {"employee_id": {"$in": ids}, "date": {"$gte": tanggal[0], "$lte": tanggal[-1]}},
            {"_id": 0, "photo": 0, "selfie_url": 0, "location": 0}).to_list(20000):
        ev[(r.get("employee_id"), str(r.get("date"))[:10])] = r
    lembur_aju: dict = {}
    for r in await db.rahaza_overtime_requests.find(
            {"employee_id": {"$in": ids}, "status": "approved", "date": {"$gte": tanggal[0], "$lte": tanggal[-1]}},
            {"_id": 0, "employee_id": 1, "date": 1, "hours": 1}).to_list(5000):
        k = (r.get("employee_id"), str(r.get("date"))[:10])
        lembur_aju[k] = lembur_aju.get(k, 0.0) + float(r.get("hours") or 0)

    baris: list = []
    hari_ini = today.isoformat()

    def tambah(kat, emp, iso, detail, saran=None):
        label, tingkat = KATEGORI[kat]
        row = {"kategori": kat, "label": label, "tingkat": tingkat, "employee_id": emp["id"],
               "karyawan": emp.get("name") or emp.get("employee_code") or emp["id"], "kode": emp.get("employee_code") or "",
               "departemen": emp.get("department") or "", "tanggal": iso, "detail": detail}
        if saran:
            row["saran_koreksi"] = saran
        baris.append(row)

    for emp in emps:
        eid = emp["id"]
        for iso in tanggal:
            c = (sel.get(eid) or {}).get(iso) or {}
            s = shifts.get(str(c.get("shift_id"))) if c.get("shift_id") else None
            libur = sr.libur_hari(kunci, iso) or ("Libur menurut jadwal" if c.get("libur_jadwal") else None)
            if s and c.get("sumber") == "jadwal" and not c.get("libur_jadwal"):
                libur = None if iso not in kunci["libur"] else libur   # dijadwalkan masuk di hari libur mingguan
            kerja = libur is None
            ck = kunci["cuti"].get((eid, iso))
            cuti_penuh = bool(ck and not ck["setengah"])
            dn = (eid, iso) in dinas
            rec = ev.get((eid, iso))
            if rec:
                st = _status(rec.get("status"))
                cin, cout = rec.get("clock_in"), rec.get("clock_out")
                late = int(rec.get("late_minutes") or 0)
                if st == "alpa":
                    if cuti_penuh:
                        tambah("alpa_padahal_cuti", emp, iso, f"Tercatat alpa, padahal {ck['label'].lower()} disetujui.")
                    elif dn:
                        tambah("alpa_padahal_dinas", emp, iso, "Tercatat alpa, padahal dinas/tugas luar disetujui.",
                               {"status": "hadir", "catatan": "Dinas/tugas luar disetujui"})
                    else:
                        tambah("alpa", emp, iso, "Tercatat alpa.")
                if st == "hadir" and cuti_penuh and cin:
                    tambah("absen_di_hari_cuti", emp, iso, f"Absen masuk {jam_lokal(cin)} pada hari {ck['label'].lower()}.")
                if st == "hadir" and late > 0:
                    jm = jam_lokal(cin)
                    if not kerja:
                        tambah("terlambat_hari_libur", emp, iso, f"Tercatat terlambat {late} menit di {libur.lower()}.",
                               {"clock_in": jm, "catatan": "Hitung ulang terlambat (hari libur)"} if jm else None)
                    elif ck and ck["setengah"] and (ck.get("periode") or "AM") == "AM":
                        tambah("terlambat_cuti_setengah", emp, iso,
                               f"Tercatat terlambat {late} menit pada {ck['label'].lower()} (pagi).",
                               {"clock_in": jm, "catatan": "Hitung ulang terlambat (cuti setengah hari pagi)"} if jm else None)
                    else:
                        tambah("terlambat", emp, iso, f"Terlambat {late} menit (masuk {jm or '—'}"
                               + (f", shift {s['kode']} {s['mulai']}" if s else "") + ").")
                if cin and not cout and iso < hari_ini:
                    saran = {"clock_out": s["selesai"], "catatan": f"Jam pulang shift {s['kode']}"} if s and s.get("selesai") else None
                    tambah("lupa_absen_pulang", emp, iso, f"Absen masuk {jam_lokal(cin)} tanpa absen pulang"
                           + (f" (shift {s['kode']} pulang {s['selesai']})." if s else "."), saran)
                jam_lembur = float(rec.get("overtime_hours") or 0)
                if jam_lembur > 0 and (eid, iso) not in lembur_aju and rec.get("overtime_paid") is None:
                    tambah("lembur_tanpa_pengajuan", emp, iso, f"{jam_lembur:g} jam lembur tercatat tanpa pengajuan disetujui.")
                if (eid, iso) in lembur_aju and not cin:
                    tambah("lembur_tanpa_absen", emp, iso, f"Pengajuan lembur {lembur_aju[(eid, iso)]:g} jam disetujui, "
                                                           "tetapi tidak ada absen masuk.")
                continue
            if (eid, iso) in lembur_aju:
                tambah("lembur_tanpa_absen", emp, iso,
                       f"Pengajuan lembur {lembur_aju[(eid, iso)]:g} jam disetujui, tetapi tidak ada catatan absen.")
            if cuti_penuh or iso >= hari_ini:
                continue
            if dn:
                tambah("tanpa_catatan_dinas", emp, iso, "Tidak ada catatan absen; dinas/tugas luar disetujui.",
                       {"status": "hadir", "catatan": "Dinas/tugas luar disetujui"})
            elif kerja:
                tambah("tanpa_catatan", emp, iso, "Hari kerja tanpa catatan absen" + (f" (shift {s['kode']})." if s else "."))

    urut = {t: i for i, t in enumerate(TINGKAT)}
    baris.sort(key=lambda r: (urut[r["tingkat"]], r["kategori"], r["tanggal"], r["karyawan"]))
    per_kat = {}
    for r in baris:
        per_kat[r["kategori"]] = per_kat.get(r["kategori"], 0) + 1
    per_kry: dict = {}
    for r in baris:
        if r["tingkat"] == "info" and r["kategori"] == "tanpa_catatan":
            continue
        k = per_kry.setdefault(r["employee_id"], {"employee_id": r["employee_id"], "karyawan": r["karyawan"],
                                                  "departemen": r["departemen"], "jumlah": 0, "kategori": {}})
        k["jumlah"] += 1
        k["kategori"][r["label"]] = k["kategori"].get(r["label"], 0) + 1
    return {
        "dari": tanggal[0], "sampai": tanggal[-1], "karyawan": len(emps), "hari": len(tanggal),
        "ringkas": [{"kategori": k, "label": KATEGORI[k][0], "tingkat": KATEGORI[k][1], "jumlah": per_kat[k]}
                    for k in KATEGORI if per_kat.get(k)],
        "per_karyawan": sorted(per_kry.values(), key=lambda x: -x["jumlah"])[:30],
        "pengecualian": baris[:MAKS_BARIS], "terpotong": len(baris) > MAKS_BARIS, "total": len(baris),
        "catatan": ("Hari kerja tanpa catatan absen TIDAK memotong gaji (keputusan owner); tetap perlu dilengkapi. "
                    "Saran koreksi diterapkan lewat jalur koreksi absen yang ada; tanggal yang sudah digaji final "
                    "menjadi penyesuaian di penggajian berikutnya."),
    }
