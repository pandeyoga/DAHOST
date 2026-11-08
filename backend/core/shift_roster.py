"""Roster shift — SATU tempat aturan jadwal shift (Tahap C audit HR, 9 Nov 2026).

Dipakai layar Shift (roster kalender, pola rotasi, salin minggu, deteksi bentrok), permintaan tukar/ganti shift
Portal Saya, dan Asisten AI ("bantu susun draf shift"). Satu master shift = `rahaza_shifts` (tidak ada master
kedua: "Pola jadwal" lama `rahaza_shift_templates` dipensiunkan).

Urutan shift yang BERLAKU per karyawan per tanggal SAMA dengan `core.attendance_rules.resolve_day_shift`
(aturan absen/terlambat): Jadwal Shift TERBIT terbaru → penugasan shift aktif (yang termuda) → shift utama
karyawan. Di sini ditambah lapis paling atas: DRAF jadwal yang sedang disusun (hanya untuk tampilan roster).

Entri jadwal (`rahaza_schedules.shifts[]`) yang ditulis modul ini:
  {id, date, employee_id, employee_code, employee_name, department, shift_id, shift_code, shift_name,
   start_time, end_time, is_overnight, color, grace_minutes?}      ← hari kerja (grace = toleransi shift bila diatur)
  {id, date, employee_id, employee_code, employee_name, department, libur: true}   ← hari libur menurut pola
Sel terkunci: cuti/izin/sakit DISETUJUI satu hari penuh (tidak bisa diberi shift) dan hari libur (kalender libur
SDM + hari libur mingguan `core.workdays`; bisa diisi bila HR sengaja memilih "isi hari libur").
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from core import workdays

HARI_KODE = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HARI_PENDEK = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")
BULAN_PENDEK = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
MAKS_HARI = 62            # satu jadwal paling panjang ±2 bulan (roster kalender tetap terbaca)
MAKS_KARYAWAN = 500
MAKS_POLA_HARI = 56       # pola rotasi paling panjang 8 minggu
ISTIRAHAT_MIN_JAM = 12    # batas peringatan istirahat antarshift (jam nyata)
LIBUR = "LIBUR"           # nilai pilihan sel "libur" di permintaan ubah sel / pola

TINGKAT = ("berat", "peringatan", "info")


class GalatRoster(Exception):
    """Galat isian roster (pesan ramah bahasa Indonesia). `status` meniru HTTP."""

    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = status
        self.pesan = pesan


# ── Tanggal ─────────────────────────────────────────────────────────────────
def tgl(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise GalatRoster(400, f"Tanggal '{v}' tidak valid. Gunakan format TTTT-BB-HH.")


def rentang(dari, sampai, maks: int = MAKS_HARI) -> list[str]:
    a, b = tgl(dari), tgl(sampai)
    if b < a:
        raise GalatRoster(400, "Tanggal selesai tidak boleh sebelum tanggal mulai.")
    n = (b - a).days + 1
    if n > maks:
        raise GalatRoster(400, f"Rentang jadwal paling panjang {maks} hari (diminta {n} hari).")
    return [(a + timedelta(days=i)).isoformat() for i in range(n)]


def senin(v) -> date:
    d = tgl(v)
    return d - timedelta(days=d.weekday())


def label_tgl(iso: str) -> str:
    d = tgl(iso)
    return f"{HARI_PENDEK[d.weekday()]} {d.day} {BULAN_PENDEK[d.month - 1]}"


def _menit(hhmm) -> Optional[int]:
    s = str(hhmm or "").strip()
    if ":" not in s:
        return None
    try:
        h, m = (int(x) for x in s.split(":")[:2])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


# ── Shift (master tunggal `rahaza_shifts`) ──────────────────────────────────
def bentuk_shift(doc: dict) -> dict:
    """Bentuk ringkas shift untuk roster: id, kode, nama, jam, warna, hari aktif, toleransi, istirahat."""
    mulai = doc.get("start_time") or doc.get("check_in_time") or ""
    selesai = doc.get("end_time") or doc.get("check_out_time") or ""
    m1, m2 = _menit(mulai), _menit(selesai)
    lewat = bool(doc.get("is_overnight")) or (m1 is not None and m2 is not None and m2 <= m1)
    tol = doc.get("toleransi_menit")
    if tol in (None, ""):
        tol = doc.get("grace_minutes")
    aktif = doc.get("status") == "active" if doc.get("status") else doc.get("active", True) is not False
    return {
        "id": str(doc.get("id")),
        "kode": doc.get("shift_code") or doc.get("code") or "",
        "nama": doc.get("shift_name") or doc.get("name") or "",
        "mulai": mulai, "selesai": selesai, "lewat_malam": lewat,
        "warna": doc.get("color") or "#64748b",
        "hari_aktif": list(doc.get("days_active") or HARI_KODE[:6]),
        "toleransi_menit": int(tol) if tol not in (None, "") else None,
        "istirahat_menit": int(doc.get("break_duration_minutes") or 0),
        "istirahat_mulai": doc.get("istirahat_mulai") or None,
        "jam_kerja": doc.get("effective_hours") if doc.get("effective_hours") is not None else doc.get("working_hours"),
        "aktif": bool(aktif),
    }


async def muat_shift(db) -> dict[str, dict]:
    """{id: bentuk_shift} — SEMUA shift (yang nonaktif tetap dikenali untuk jadwal lama)."""
    out = {}
    async for d in db.rahaza_shifts.find({}, {"_id": 0}):
        if d.get("id") is not None:
            out[str(d["id"])] = bentuk_shift(d)
    return out


def shift_dari_kode(shifts: dict, kode) -> Optional[dict]:
    k = str(kode or "").strip().upper()
    if not k:
        return None
    for s in shifts.values():
        if str(s["kode"]).upper() == k:
            return s
    return None


def entri_jadwal(emp: dict, iso: str, shift: Optional[dict]) -> dict:
    """Entri `rahaza_schedules.shifts[]` — kerja (dengan `shift_id`) atau libur."""
    e = {"id": str(uuid.uuid4()), "date": iso, "employee_id": emp.get("id"),
         "employee_code": emp.get("employee_code") or "", "employee_name": emp.get("name") or "",
         "department": emp.get("department") or ""}
    if not shift:
        e["libur"] = True
        return e
    e.update({"shift_id": shift["id"], "shift_code": shift["kode"], "shift_name": shift["nama"],
              "start_time": shift["mulai"], "end_time": shift["selesai"], "is_overnight": shift["lewat_malam"],
              "color": shift["warna"]})
    if shift.get("toleransi_menit") is not None:
        # dibaca aturan absen (`core.attendance_rules._shape(grace=…)`) untuk hari yang dijadwalkan
        e["grace_minutes"] = int(shift["toleransi_menit"])
    return e


def shift_entri(e: dict, shifts: dict) -> Optional[dict]:
    """Shift dari satu entri jadwal: `shift_id` → kode (jadwal lama tanpa id) → None (libur / tak dikenal)."""
    if not e or e.get("libur"):
        return None
    s = shifts.get(str(e.get("shift_id"))) if e.get("shift_id") is not None else None
    return s or shift_dari_kode(shifts, e.get("shift_code"))


# ── Karyawan ────────────────────────────────────────────────────────────────
async def karyawan_lingkup(db, *, departemen: Optional[str] = None, lokasi: Optional[str] = None,
                           employee_ids: Optional[Iterable[str]] = None, cari: Optional[str] = None,
                           batas: int = MAKS_KARYAWAN) -> list[dict]:
    """Karyawan AKTIF (`active` ≠ false) menurut departemen / lokasi / pilihan baris, urut kode lalu nama."""
    q: dict = {"active": {"$ne": False}}
    if departemen:
        q["department"] = departemen
    if lokasi:
        q["location_id"] = lokasi
    ids = [str(i) for i in (employee_ids or []) if i]
    if employee_ids is not None:
        q["id"] = {"$in": ids}
    rows = await db.rahaza_employees.find(q, {
        "_id": 0, "id": 1, "employee_code": 1, "name": 1, "department": 1, "location_id": 1, "shift_id": 1,
        "manager_id": 1, "user_id": 1}).to_list(batas)
    if cari:
        c = str(cari).strip().lower()
        rows = [r for r in rows if c in str(r.get("name") or "").lower() or c in str(r.get("employee_code") or "").lower()]
    return sorted(rows, key=lambda r: (str(r.get("employee_code") or "~"), str(r.get("name") or "")))


# ── Kunci: cuti disetujui & hari libur ──────────────────────────────────────
async def kunci_hari(db, emp_ids: list, tanggal: list[str]) -> dict:
    """{cuti: {(eid, iso): {label, setengah}}, libur: {iso: label}, off: set(weekday)} untuk rentang `tanggal`."""
    out = {"cuti": {}, "libur": {}, "off": set()}
    if not tanggal:
        return out
    dari, sampai = tanggal[0], tanggal[-1]
    cal = await workdays.get_work_calendar(db)
    out["off"] = set(cal["off_weekdays"])
    for h in await workdays.holidays_between(db, dari, sampai, limit=200):
        out["libur"][h["date"]] = h.get("name") or "Hari libur"
    if not emp_ids:
        return out
    jenis = {}
    async for t in db.rahaza_leave_types.find({}, {"_id": 0, "id": 1, "name": 1}):
        jenis[t.get("id")] = t.get("name")
    rows = await db.rahaza_leave_requests.find(
        {"employee_id": {"$in": list(emp_ids)}, "status": "approved",
         "from_date": {"$lte": sampai}, "to_date": {"$gte": dari}},
        {"_id": 0, "employee_id": 1, "from_date": 1, "to_date": 1, "is_half_day": 1, "half_day_period": 1,
         "request_type": 1, "leave_kind": 1, "leave_type_id": 1, "leave_type_name": 1}).to_list(5000)
    lbl = {"cuti": "Cuti", "izin": "Izin", "sakit": "Sakit"}
    for r in rows:
        a, b = tgl(r["from_date"]), tgl(r.get("to_date") or r["from_date"])
        nama = r.get("leave_type_name") or jenis.get(r.get("leave_type_id")) or \
            lbl.get(str(r.get("leave_kind") or r.get("request_type") or "cuti"), "Cuti")
        d = a
        while d <= b:
            iso = d.isoformat()
            if dari <= iso <= sampai:
                setengah = bool(r.get("is_half_day"))
                out["cuti"][(r["employee_id"], iso)] = {
                    "label": nama + (" setengah hari" if setengah else ""), "setengah": setengah,
                    "periode": r.get("half_day_period") if setengah else None}
            d += timedelta(days=1)
    return out


def libur_hari(kunci: dict, iso: str) -> Optional[str]:
    """Label hari libur (kalender libur SDM atau libur mingguan) atau None."""
    if iso in kunci["libur"]:
        return kunci["libur"][iso]
    if tgl(iso).weekday() in kunci["off"]:
        return "Libur mingguan"
    return None


# ── Shift berlaku (urutan sama dengan aturan absen) ─────────────────────────
async def jadwal_terbit(db, dari: str, sampai: str, kecuali: Optional[str] = None) -> list[dict]:
    """Jadwal TERBIT yang beririsan rentang, terbaru dulu (yang terbaru menang — sama dengan aturan absen)."""
    q = {"status": "published", "start_date": {"$lte": sampai}, "end_date": {"$gte": dari}}
    rows = await db.rahaza_schedules.find(q, {"_id": 0}).sort("published_at", -1).to_list(100)
    return [r for r in rows if r.get("id") != kecuali]


def peta_entri(jadwal: list[dict]) -> dict:
    """{(eid, iso): (entri, jadwal_id)} — jadwal pertama di daftar menang."""
    out: dict = {}
    for sc in jadwal:
        for e in sc.get("shifts") or []:
            k = (e.get("employee_id"), str(e.get("date") or "")[:10])
            if k not in out:
                out[k] = (e, sc.get("id"))
    return out


async def penugasan_aktif(db, emp_ids: list, dari: str, sampai: str) -> dict:
    """{eid: [penugasan aktif yang beririsan rentang, termuda dulu]}."""
    out: dict = {}
    if not emp_ids:
        return out
    rows = await db.hr_shift_assignments.find({
        "employee_id": {"$in": list(emp_ids)}, "status": "active", "effective_from": {"$lte": sampai},
        "$or": [{"effective_until": None}, {"effective_until": ""}, {"effective_until": {"$gte": dari}}],
    }, {"_id": 0}).to_list(5000)
    for a in sorted(rows, key=lambda a: str(a.get("effective_from") or ""), reverse=True):
        out.setdefault(a.get("employee_id"), []).append(a)
    return out


def _penugasan_pada(daftar: list, iso: str) -> Optional[dict]:
    for a in daftar or []:
        if str(a.get("effective_from") or "") <= iso and (not a.get("effective_until") or str(a["effective_until"]) >= iso):
            return a
    return None


async def sel_berlaku(db, emps: list, tanggal: list[str], shifts: dict, *, draf: Optional[dict] = None) -> dict:
    """{eid: {iso: {shift_id|None, sumber, libur_jadwal}}} — shift yang berlaku per sel.

    sumber: "draf" (jadwal yang sedang disusun) · "jadwal" (jadwal terbit) · "penugasan" · "karyawan" · None."""
    if not tanggal:
        return {}
    ids = [e["id"] for e in emps]
    terbit = peta_entri(await jadwal_terbit(db, tanggal[0], tanggal[-1], kecuali=(draf or {}).get("id")))
    dr = peta_entri([draf]) if draf else {}
    tugas = await penugasan_aktif(db, ids, tanggal[0], tanggal[-1])
    out: dict = {}
    for emp in emps:
        eid = emp["id"]
        baris = out.setdefault(eid, {})
        for iso in tanggal:
            sel = {"shift_id": None, "sumber": None, "libur_jadwal": False}
            pakai = dr.get((eid, iso)) if draf else None
            sumber = "draf" if pakai else None
            if not pakai and (eid, iso) in terbit:
                pakai, sumber = terbit[(eid, iso)], "jadwal"
            if pakai:
                e = pakai[0]
                if e.get("libur"):
                    sel.update(sumber=sumber, libur_jadwal=True)
                    baris[iso] = sel
                    continue
                s = shift_entri(e, shifts)
                if s:
                    sel.update(shift_id=s["id"], sumber=sumber)
                    baris[iso] = sel
                    continue
            a = _penugasan_pada(tugas.get(eid), iso)
            if a and str(a.get("shift_id")) in shifts:
                sel.update(shift_id=str(a.get("shift_id")), sumber="penugasan")
            elif emp.get("shift_id") and str(emp["shift_id"]) in shifts:
                sel.update(shift_id=str(emp["shift_id"]), sumber="karyawan")
            baris[iso] = sel
    return out


# ── Pola rotasi ─────────────────────────────────────────────────────────────
def periksa_urutan(urutan, shifts: dict) -> list:
    """Urutan pola = daftar per hari: id shift atau None (libur). Panjang kelipatan 7, 7–56 hari."""
    if not isinstance(urutan, list) or not urutan:
        raise GalatRoster(400, "Pola wajib berisi minimal satu minggu.")
    if len(urutan) % 7 or len(urutan) > MAKS_POLA_HARI:
        raise GalatRoster(400, f"Pola harus berisi minggu penuh (7, 14, …, {MAKS_POLA_HARI} hari).")
    out = []
    for i, v in enumerate(urutan):
        if v in (None, "", LIBUR):
            out.append(None)
            continue
        s = shifts.get(str(v))
        if not s or not s["aktif"]:
            raise GalatRoster(400, f"Shift di hari ke-{i + 1} pola tidak ditemukan atau sudah nonaktif.")
        out.append(s["id"])
    return out


def shift_pola(pola: dict, mulai_pola: date, iso: str, geser: int = 0) -> Optional[str]:
    """Id shift (atau None = libur) dari pola untuk tanggal `iso`; hari ke-0 pola = `mulai_pola` (+ geser hari)."""
    urutan = pola.get("urutan") or []
    if not urutan:
        return None
    i = ((tgl(iso) - mulai_pola).days + int(geser or 0)) % len(urutan)
    return urutan[i]


def shift_bekerja(shift: Optional[dict], iso: str) -> bool:
    return bool(shift) and HARI_KODE[tgl(iso).weekday()] in (shift.get("hari_aktif") or HARI_KODE[:6])


async def susun_entri(db, *, emps: list, tanggal: list[str], shifts: dict, cara: str, pola: Optional[dict] = None,
                      mulai_pola=None, geser_per_karyawan: Optional[dict] = None, shift_id: Optional[str] = None,
                      salin_dari=None, isi_libur: bool = False) -> dict:
    """Susun entri DRAF jadwal. `cara`:
       pola     — pola rotasi (`pola.urutan`, hari ke-0 = `mulai_pola`, geser per karyawan opsional);
       shift    — satu shift untuk semua (hari di luar "hari kerja" shift = libur);
       berlaku  — salin shift yang berlaku sekarang (penugasan / shift utama) supaya tinggal diubah;
       salin    — salin minggu sumber (`salin_dari`, tanggal di minggu itu) berulang ke seluruh rentang.
    Sel cuti satu hari penuh dilewati (tidak dijadwalkan); hari libur kalender/mingguan diberi entri libur kecuali
    `isi_libur`. Return {entri, dilewati: [{employee_id, date, alasan}]}."""
    if cara not in ("pola", "shift", "berlaku", "salin"):
        raise GalatRoster(400, "Cara menyusun jadwal tidak dikenal.")
    kunci = await kunci_hari(db, [e["id"] for e in emps], tanggal)
    sumber_sel: dict = {}
    if cara == "pola":
        if not pola:
            raise GalatRoster(400, "Pilih pola rotasi.")
        mulai = tgl(mulai_pola) if mulai_pola else tgl(tanggal[0])
    elif cara == "shift":
        s_pilih = shifts.get(str(shift_id)) if shift_id else None
        if not s_pilih or not s_pilih["aktif"]:
            raise GalatRoster(400, "Pilih shift yang masih aktif.")
    elif cara == "berlaku":
        sumber_sel = await sel_berlaku(db, emps, tanggal, shifts)
    else:
        if not salin_dari:
            raise GalatRoster(400, "Pilih minggu yang akan disalin.")
        m0 = senin(salin_dari)
        src_tgl = [(m0 + timedelta(days=i)).isoformat() for i in range(7)]
        sumber_sel = await sel_berlaku(db, emps, src_tgl, shifts)
    entri, dilewati = [], []
    for emp in emps:
        eid = emp["id"]
        for iso in tanggal:
            ck = kunci["cuti"].get((eid, iso))
            if ck and not ck["setengah"]:
                dilewati.append({"employee_id": eid, "date": iso, "alasan": ck["label"]})
                continue
            if cara == "pola":
                sid = shift_pola(pola, mulai, iso, (geser_per_karyawan or {}).get(eid, 0))
                s = shifts.get(str(sid)) if sid else None
            elif cara == "shift":
                s = s_pilih if shift_bekerja(s_pilih, iso) else None
            elif cara == "berlaku":
                sid = (sumber_sel.get(eid, {}).get(iso) or {}).get("shift_id")
                s = shifts.get(str(sid)) if sid else None
                s = s if shift_bekerja(s, iso) else None
            else:
                src = (senin(salin_dari) + timedelta(days=tgl(iso).weekday())).isoformat()
                sel = sumber_sel.get(eid, {}).get(src) or {}
                s = shifts.get(str(sel.get("shift_id"))) if sel.get("shift_id") and not sel.get("libur_jadwal") else None
            lib = libur_hari(kunci, iso)
            if s and lib and not isi_libur and iso in kunci["libur"]:
                # libur kalender (nasional/cuti bersama/perusahaan) tidak dijadwalkan kecuali HR memilihnya
                s = None
            entri.append(entri_jadwal(emp, iso, s))
    return {"entri": entri, "dilewati": dilewati}


def ringkas_jadwal(entri: list) -> dict:
    kerja = [e for e in entri if not e.get("libur")]
    per_shift: dict = {}
    for e in kerja:
        per_shift[e.get("shift_code") or "?"] = per_shift.get(e.get("shift_code") or "?", 0) + 1
    return {"total_shifts": len(kerja), "hari_libur": len(entri) - len(kerja),
            "employees_scheduled": len({e.get("employee_id") for e in kerja}),
            "per_shift": [{"kode": k, "jumlah": v} for k, v in sorted(per_shift.items())]}


# ── Deteksi bentrok ─────────────────────────────────────────────────────────
def _instan(iso: str, hhmm: str, tambah_hari: int = 0) -> Optional[datetime]:
    m = _menit(hhmm)
    if m is None:
        return None
    d = tgl(iso) + timedelta(days=tambah_hari)
    return datetime(d.year, d.month, d.day) + timedelta(minutes=m)


def jam_istirahat(sebelum: dict, iso_sebelum: str, sesudah: dict, iso_sesudah: str) -> Optional[float]:
    """Jam istirahat nyata antara akhir shift `sebelum` dan awal shift `sesudah`."""
    akhir = _instan(iso_sebelum, sebelum.get("selesai"), 1 if sebelum.get("lewat_malam") else 0)
    awal = _instan(iso_sesudah, sesudah.get("mulai"))
    if not akhir or not awal:
        return None
    return round((awal - akhir).total_seconds() / 3600, 1)


def cari_bentrok(sel: dict, emps: list, tanggal: list[str], shifts: dict, kunci: dict,
                 batas_istirahat: float = ISTIRAHAT_MIN_JAM) -> list[dict]:
    """Bentrok jadwal per sel (urut karyawan, tanggal). `sel` = hasil `sel_berlaku`.

    berat      — dijadwalkan pada cuti/izin/sakit DISETUJUI satu hari penuh (jadwal tidak berlaku hari itu)
    peringatan — masuk di hari libur kalender / di luar hari kerja shift; istirahat antarshift < 12 jam nyata
    info       — cuti/izin setengah hari pada hari yang dijadwalkan (jam masuk acuan mengikuti aturan cuti)"""
    out = []
    nama = {e["id"]: (e.get("name") or e.get("employee_code") or e["id"]) for e in emps}
    for emp in emps:
        eid = emp["id"]
        baris = sel.get(eid) or {}
        sebelum = None
        for iso in tanggal:
            c = baris.get(iso) or {}
            s = shifts.get(str(c.get("shift_id"))) if c.get("shift_id") else None
            dasar = {"employee_id": eid, "karyawan": nama.get(eid), "date": iso, "tanggal": label_tgl(iso)}
            if s:
                ck = kunci["cuti"].get((eid, iso))
                if ck and not ck["setengah"]:
                    out.append({**dasar, "jenis": "cuti", "tingkat": "berat",
                                "pesan": f"Dijadwalkan {s['kode']} padahal {ck['label'].lower()} sudah disetujui."})
                elif ck:
                    out.append({**dasar, "jenis": "cuti_setengah", "tingkat": "info",
                                "pesan": f"{ck['label']} pada hari shift {s['kode']}."})
                if iso in kunci["libur"]:
                    out.append({**dasar, "jenis": "libur", "tingkat": "peringatan",
                                "pesan": f"Masuk {s['kode']} di hari libur ({kunci['libur'][iso]})."})
                elif not shift_bekerja(s, iso):
                    out.append({**dasar, "jenis": "hari_kerja", "tingkat": "peringatan",
                                "pesan": f"{HARI_PENDEK[tgl(iso).weekday()]} bukan hari kerja shift {s['kode']}."})
                if sebelum:
                    jam = jam_istirahat(sebelum[1], sebelum[0], s, iso)
                    if jam is not None and jam < batas_istirahat:
                        out.append({**dasar, "jenis": "istirahat", "tingkat": "peringatan",
                                    "pesan": f"Istirahat dari shift {sebelum[1]['kode']} sebelumnya hanya "
                                             f"{str(jam).replace('.', ',')} jam (kurang dari {int(batas_istirahat)} jam)."})
                sebelum = (iso, s)
            else:
                sebelum = None if not c.get("shift_id") else sebelum
    urut = {t: i for i, t in enumerate(TINGKAT)}
    return sorted(out, key=lambda b: (urut.get(b["tingkat"], 9), str(b.get("karyawan")), b["date"]))


def hitung_bentrok(bentrok: list) -> dict:
    out = {t: 0 for t in TINGKAT}
    for b in bentrok:
        out[b["tingkat"]] = out.get(b["tingkat"], 0) + 1
    return out
