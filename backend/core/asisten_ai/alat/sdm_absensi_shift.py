"""Alat Asisten AI — SDM: absensi, shift, payroll (audit HR Tahap D, 9 Nov 2026). Ruang `sdm` (Portal SDM › AI SDM).

  rekap_absensi_pengecualian      (baca, kode)  siapa terlambat / alpa / tanpa catatan / lupa absen pulang, dicocokkan
                                                dengan cuti, dinas, libur, jadwal — `GET /api/hr/absensi/pengecualian`
                                                (aturan deterministik `core/absensi_pengecualian.py`; AI hanya merangkum)
  cakupan_shift                   (baca, kode)  jumlah orang per tanggal per shift, per departemen, karyawan tanpa shift,
                                                bentrok, pola rotasi — `GET /api/hr/shift-scheduler/roster` + `/pola`
  cek_payroll_sebelum_finalisasi  (baca)        anomali run gaji DRAF vs run final sebelumnya (`_bantu_sdm.anomali_payroll`)
  terapkan_koreksi_absen          (tindakan, MENENGAH) jalur koreksi absen yang ada: `POST /api/rahaza/attendance/corrections`
                                                atas nama karyawan lalu `/approve`. Tanggal yang sudah digaji final → otomatis
                                                penyesuaian di penggajian berikutnya (kunci payroll dihormati endpoint).
  susun_draf_shift                (tindakan, rendah) pratinjau `GET …/schedules/pratinjau` → kartu → `POST …/schedules` = DRAF
                                                (bukan terbit). Bisa dibalikkan: draf dihapus.
Aturan privasi: nama asli hanya untuk owner/superadmin/SDM (`boleh_sdm_penuh`), lainnya kode KRY-xxx; nominal gaji per
orang hanya `PERAN_GAJI`. Semua tulisan lewat endpoint layar dengan token pengguna — hak akses endpoint berlaku.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from core.asisten_ai.alat_base import AlatError, alat, tindakan
from core.asisten_ai.alat._bantu_laporan import (
    SKEMA_PERIODE, boleh_sdm_penuh, coba, hari_ini, pangkas, periode, samaran, saring_pii,
)
from core.asisten_ai.alat._bantu_sdm import anomali_payroll, cakupan_roster, ringkas_anomali

P_PENGECUALIAN = "/api/hr/absensi/pengecualian"
P_ABSEN = "/api/rahaza/attendance"
P_KOREKSI = "/api/rahaza/attendance/corrections"
P_ROSTER = "/api/hr/shift-scheduler/roster"
P_POLA = "/api/hr/shift-scheduler/pola"
P_PRATINJAU = "/api/hr/shift-scheduler/schedules/pratinjau"
P_JADWAL = "/api/hr/shift-scheduler/schedules"
P_SHIFT = "/api/hr/shifts"
P_RUN = "/api/rahaza/payroll-runs"

_JAM_RX = r"^([01]\d|2[0-3]):[0-5]\d$"
_TGL_RX = r"^\d{4}-\d{2}-\d{2}$"
_ID_RX = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
BATAS_BARIS_LANGSUNG = 60
MAKS_KOREKSI = 30
STATUS_KOREKSI = ("hadir", "alpa", "libur")
HARI = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")
BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
STATUS_RUN_FINAL = ("finalized", "paid", "posted", "final")


def _tgl(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{HARI[d.weekday()]} {d.day} {BULAN[d.month - 1]} {d.year}"


def _nama_aman(ctx, ps, nama):
    return nama if boleh_sdm_penuh(ctx) else (ps.code(nama, "karyawan") if nama else None)


async def _akhiri(ctx, hasil: dict, daftar=()) -> dict:
    if not boleh_sdm_penuh(ctx):
        hasil["catatan_nama"] = "Nama karyawan disamarkan (kode KRY-xxx) sesuai hak akses Anda."
        hasil = await saring_pii(ctx, hasil)
    return pangkas(hasil, daftar)


def _tolak_gabungan(ctx) -> None:
    if str(getattr(ctx, "cv", "") or "").upper() == "ALL":
        from core.entities import READONLY_ALL_MSG
        raise AlatError(400, READONLY_ALL_MSG + " Setelah itu minta lagi.")


def _periode_maks(args: dict, ctx, *, hari_bawaan: int = 7, maks: int = 62, ke_depan: bool = False) -> tuple:
    """(dari, sampai) dari `dari`/`sampai`/`bulan`; bawaan 7 hari terakhir (atau 7 hari ke depan untuk shift)."""
    args = args or {}
    today = hari_ini(ctx)
    if args.get("dari") or args.get("sampai") or args.get("bulan"):
        p = periode(args, ctx) if not ke_depan else None
        if ke_depan:
            if not (args.get("dari") and args.get("sampai")):
                raise AlatError(400, "Isi 'dari' dan 'sampai' (TTTT-BB-HH).")
            a, b = date.fromisoformat(args["dari"]), date.fromisoformat(args["sampai"])
        else:
            a, b = date.fromisoformat(p["dari"]), date.fromisoformat(p["sampai"])
    elif ke_depan:
        a = today + timedelta(days=(7 - today.weekday()) % 7 or 7)   # Senin depan
        b = a + timedelta(days=hari_bawaan - 1)
    else:
        a, b = today - timedelta(days=hari_bawaan - 1), today
    if b < a:
        raise AlatError(400, "'sampai' tidak boleh sebelum 'dari'.")
    if (b - a).days + 1 > maks:
        raise AlatError(400, f"Rentang paling panjang {maks} hari. Persempit periodenya.")
    return a.isoformat(), b.isoformat()


# ═══ Rekap absensi & pengecualian ═══════════════════════════════════════════════════════════════════════
@alat(
    name="rekap_absensi_pengecualian",
    kind="read",
    label="Membaca pengecualian absensi",
    description=(
        "Rekap PENGECUALIAN absensi per karyawan per hari (bawaan 7 hari terakhir; paling lama 62 hari): lupa absen "
        "pulang, terlambat (dipisah: hari kerja biasa, hari libur, cuti setengah hari pagi), alpa (dipisah: padahal cuti "
        "atau dinas disetujui), hari kerja tanpa catatan absen, tanpa catatan padahal dinas, absen di hari cuti, lembur "
        "tanpa pengajuan, dan pengajuan lembur tanpa absen — sudah dicocokkan dengan cuti/izin disetujui, dinas, kalender "
        "libur, dan jadwal shift. Tiap baris bertingkat (perlu_tindakan · periksa · info) dan, bila aman, membawa "
        "`saran_koreksi` + `employee_id` yang bisa langsung dipakai `terapkan_koreksi_absen`. Hari tanpa catatan tidak "
        "memotong gaji. Nama asli hanya untuk owner/SDM."),
    input_schema={"type": "object", "properties": {
        **SKEMA_PERIODE,
        "departemen": {"type": "string", "description": "Nama departemen (opsional)."},
        "kategori": {"type": "array", "items": {"type": "string"}, "maxItems": 12,
                     "description": "Saring kategori, mis. ['lupa_absen_pulang','terlambat'] (opsional)."},
    }, "additionalProperties": False},
    domain="sdm",
    kode=True,
)
async def rekap_absensi_pengecualian(ctx, args: dict) -> dict:
    dari, sampai = _periode_maks(args, ctx)
    params = {"dari": dari, "sampai": sampai}
    if (args or {}).get("departemen"):
        params["departemen"] = str(args["departemen"])[:80]
    d = await ctx.api("GET", P_PENGECUALIAN, params=params)
    rows = d.get("pengecualian") or []
    kat = set((args or {}).get("kategori") or [])
    if kat:
        rows = [r for r in rows if r.get("kategori") in kat]
    ps = samaran(ctx)
    batas = len(rows) if getattr(ctx, "pemanggil", "langsung") == "kode" else BATAS_BARIS_LANGSUNG
    out_rows = []
    for r in rows[:batas]:
        x = {"tingkat": r["tingkat"], "kategori": r["kategori"], "label": r["label"], "tanggal": r["tanggal"],
             "karyawan": _nama_aman(ctx, ps, r.get("karyawan")), "employee_id": r.get("employee_id"),
             "departemen": r.get("departemen"), "detail": r.get("detail")}
        if r.get("saran_koreksi"):
            x["saran_koreksi"] = r["saran_koreksi"]
        out_rows.append(x)
    hasil = {
        "periode": {"dari": d.get("dari"), "sampai": d.get("sampai"), "hari": d.get("hari")},
        "karyawan_diperiksa": d.get("karyawan"),
        "ringkas": d.get("ringkas") or [],
        "per_karyawan": [{"karyawan": _nama_aman(ctx, ps, k.get("karyawan")), "employee_id": k.get("employee_id"),
                          "departemen": k.get("departemen"), "jumlah": k.get("jumlah"), "kategori": k.get("kategori")}
                         for k in (d.get("per_karyawan") or [])[:15]],
        "pengecualian": out_rows,
        "jumlah_baris": len(rows),
        "bisa_dikoreksi": sum(1 for r in rows if r.get("saran_koreksi")),
        "catatan": d.get("catatan"),
        "_sumber": "Rekap absensi & pengecualian (SDM)",
    }
    if len(rows) > len(out_rows):
        hasil["catatan_baris"] = (f"Menampilkan {len(out_rows)} dari {len(rows)} baris (urut tingkat). Saring kategori "
                                  "atau departemen, atau olah lengkap dengan kode, untuk sisanya.")
    return await _akhiri(ctx, hasil, ("pengecualian", "per_karyawan"))


# ═══ Cakupan shift ═════════════════════════════════════════════════════════════════════════════════════
@alat(
    name="cakupan_shift",
    kind="read",
    label="Membaca cakupan shift",
    description=(
        "Cakupan roster shift untuk rentang (bawaan Senin–Minggu minggu depan; paling lama 62 hari): jumlah orang per "
        "tanggal per shift, per departemen, karyawan yang belum punya shift di hari kerja, jumlah & contoh bentrok "
        "(cuti/libur/istirahat < 12 jam), daftar shift (kode, jam, hari kerja, toleransi), dan pola rotasi yang ada. "
        "Sumber shift: jadwal terbit → penugasan → shift utama karyawan (atau draf bila `jadwal_id` diisi). Dipakai "
        "sebelum menyiapkan `susun_draf_shift`."),
    input_schema={"type": "object", "properties": {
        "dari": {"type": "string", "pattern": _TGL_RX, "description": "Awal TTTT-BB-HH."},
        "sampai": {"type": "string", "pattern": _TGL_RX, "description": "Akhir TTTT-BB-HH."},
        "departemen": {"type": "string"},
        "jadwal_id": {"type": "string", "pattern": _ID_RX, "description": "Id draf jadwal (opsional)."},
    }, "additionalProperties": False},
    domain="sdm",
    kode=True,
)
async def cakupan_shift(ctx, args: dict) -> dict:
    dari, sampai = _periode_maks(args, ctx, ke_depan=True)
    params = {"dari": dari, "sampai": sampai}
    if (args or {}).get("departemen"):
        params["department"] = str(args["departemen"])[:80]
    if (args or {}).get("jadwal_id"):
        params["jadwal_id"] = args["jadwal_id"]
    r = (await ctx.api("GET", P_ROSTER, params=params)).get("data") or {}
    pola, _ = await coba(ctx, "GET", P_POLA)
    ps = samaran(ctx)
    cak = cakupan_roster(r)
    hasil = {
        "periode": {"dari": dari, "sampai": sampai}, "karyawan": len(r.get("karyawan") or []),
        "shift": [{"kode": s["kode"], "nama": s["nama"], "jam": f"{s['mulai']}–{s['selesai']}", "hari_kerja": s.get("hari_aktif"),
                   "toleransi_menit": s.get("toleransi_menit"), "id": s["id"]} for s in r.get("shift") or []],
        "pola_rotasi": [{"id": p.get("id"), "nama": p.get("nama"), "minggu": p.get("minggu")}
                        for p in ((pola or {}).get("data") or [])],
        "per_tanggal": cak["per_tanggal"], "per_departemen": cak["per_departemen"],
        "tanpa_shift": [{**x, "karyawan": _nama_aman(ctx, ps, x["karyawan"])} for x in cak["tanpa_shift"][:40]],
        "jumlah_tanpa_shift": len(cak["tanpa_shift"]),
        "bentrok": {"jumlah": r.get("jumlah_bentrok"),
                    "contoh": [{"tanggal": b.get("date"), "karyawan": _nama_aman(ctx, ps, b.get("karyawan")),
                                "tingkat": b.get("tingkat"), "pesan": b.get("pesan")} for b in (r.get("bentrok") or [])[:20]]},
        "_sumber": "Roster shift (SDM)",
    }
    if r.get("jadwal"):
        hasil["draf"] = {"id": r["jadwal"].get("id"), "judul": r["jadwal"].get("judul")}
    return await _akhiri(ctx, hasil, ("per_tanggal", "tanpa_shift", "per_departemen"))


# ═══ Cek payroll sebelum finalisasi ════════════════════════════════════════════════════════════════════
@alat(
    name="cek_payroll_sebelum_finalisasi",
    kind="read",
    label="Memeriksa run gaji sebelum finalisasi",
    description=(
        "Periksa run gaji DRAF (bawaan run draf terbaru) sebelum difinalisasi: gaji bersih minus, gaji dibayar tanpa "
        "catatan absen, bonus kehadiran hangus karena tanpa catatan, bruto berubah > ambang % dari run final sebelumnya, "
        "PPh21 lompat, lembur > 4 jam/hari kerja atau > 18 jam/minggu, penyesuaian pendapatan manual, dan peringatan "
        "hitungan gaji — dengan penjelasan per karyawan. Hanya owner dan SDM inti (gaji rahasia)."),
    input_schema={"type": "object", "properties": {
        "run_id": {"type": "string", "pattern": _ID_RX, "description": "Id run (opsional; bawaan run draf terbaru)."},
        "ambang_persen": {"type": "number", "minimum": 5, "maximum": 100,
                          "description": "Ambang perubahan bruto (persen), bawaan 20."},
    }, "additionalProperties": False},
    domain="sdm",
)
async def cek_payroll_sebelum_finalisasi(ctx, args: dict) -> dict:
    if not getattr(ctx, "boleh_gaji", False):
        raise AlatError(403, "Pemeriksaan gaji per karyawan hanya untuk owner dan SDM inti (gaji bersifat rahasia).")
    args = args or {}
    runs = await ctx.api("GET", P_RUN, params={"limit": 30})
    runs = runs if isinstance(runs, list) else (runs or {}).get("items") or []
    if args.get("run_id"):
        run = next((r for r in runs if r.get("id") == args["run_id"]), None) or {"id": args["run_id"]}
    else:
        run = next((r for r in runs if r.get("status") == "draft"), None)
        if not run:
            return {"catatan": "Tidak ada run gaji berstatus draf. Buat run di Penggajian › Proses gaji dulu.",
                    "_sumber": "Penggajian"}
    det = await ctx.api("GET", f"{P_RUN}/{run['id']}")
    run = det.get("run") or run
    slips = det.get("payslips") or []
    lalu = next((r for r in runs if r.get("status") in STATUS_RUN_FINAL and r.get("id") != run.get("id")
                 and str(r.get("period_to") or "") < str(run.get("period_from") or "")), None)
    slips_lalu = []
    if lalu:
        d2, _ = await coba(ctx, "GET", f"{P_RUN}/{lalu['id']}")
        slips_lalu = (d2 or {}).get("payslips") or []
    anom = anomali_payroll(slips, slips_lalu, ambang_bruto=float(args.get("ambang_persen") or 20))
    hasil = {
        "run": {"id": run.get("id"), "nomor": run.get("run_number"), "periode": f"{run.get('period_from')} s.d. {run.get('period_to')}",
                "status": run.get("status"), "slip": len(slips),
                "total_bruto": round(sum(float(s.get("gross_pay") or 0) for s in slips)),
                "total_neto": round(sum(float(s.get("net_pay") or 0) for s in slips))},
        "pembanding": ({"nomor": lalu.get("run_number"), "periode": f"{lalu.get('period_from')} s.d. {lalu.get('period_to')}"}
                       if lalu else "Belum ada run final sebelumnya — perubahan bruto/PPh21 tidak bisa dibandingkan."),
        "ringkas": ringkas_anomali(anom),
        "anomali": anom[:80],
        "jumlah_anomali": len(anom),
        "saran": ("Perbaiki absensi/penyesuaian yang perlu, lalu Hitung ulang run sebelum Finalisasi. Hari kerja tanpa "
                  "catatan absen tidak memotong gaji (keputusan owner)."),
        "_sumber": "Penggajian (run draf)",
    }
    return pangkas(hasil, ("anomali",))


# ═══ Tindakan: terapkan koreksi absen ══════════════════════════════════════════════════════════════════
def _jam_kosong(v) -> str:
    return v or "—"


async def _rekam(ctx, eid: str, iso: str) -> dict:
    d = await ctx.api("GET", P_ABSEN, params={"employee_id": eid, "date": iso, "limit": 1})
    items = (d or {}).get("items") or []
    return items[0] if items else {}


async def _terkunci(ctx, eid: str, iso: str) -> bool:
    db = getattr(ctx, "db", None)
    if db is None:
        return False
    try:
        from core.attendance_rules import attendance_lock
        return bool(await attendance_lock(db, eid, iso))
    except Exception:  # noqa: BLE001 — info kartu saja; endpoint tetap penentu
        return False


def _ringkas_rekam(r: dict) -> str:
    if not r:
        return "tidak ada catatan"
    from core.absensi_pengecualian import jam_lokal
    st = (r.get("status") or "hadir")
    lt = int(r.get("late_minutes") or 0)
    return (f"{st} · masuk {_jam_kosong(jam_lokal(r.get('clock_in')))} · pulang {_jam_kosong(jam_lokal(r.get('clock_out')))}"
            + (f" · terlambat {lt} mnt" if lt else ""))


def _ringkas_koreksi(k: dict) -> str:
    bag = []
    if k.get("status"):
        bag.append(k["status"])
    if k.get("jam_masuk"):
        bag.append(f"masuk {k['jam_masuk']}")
    if k.get("jam_pulang"):
        bag.append(f"pulang {k['jam_pulang']}")
    return " · ".join(bag) + (" (terlambat dihitung ulang)" if k.get("jam_masuk") else "")


@tindakan(
    name="terapkan_koreksi_absen",
    label="Menerapkan koreksi absen",
    description=(
        "Terapkan koreksi absen (paling banyak 30 baris) lewat jalur koreksi yang sudah ada: tiap baris dibuat sebagai "
        "pengajuan koreksi atas nama karyawan lalu disetujui (absensi diperbarui dan terlambat dihitung ulang). Tanggal "
        "yang sudah masuk gaji final TIDAK diubah: otomatis menjadi penyesuaian di penggajian berikutnya. Isi per baris: "
        "employee_id + tanggal + minimal satu dari status (hadir/alpa/libur), jam_masuk, jam_pulang (JJ:MM WIB). Cuti/izin/"
        "sakit TIDAK lewat sini (pakai pengajuan cuti). Ambil baris dari `saran_koreksi` hasil `rekap_absensi_pengecualian`."),
    input_schema={"type": "object", "properties": {
        "koreksi": {"type": "array", "minItems": 1, "maxItems": MAKS_KOREKSI, "items": {
            "type": "object", "properties": {
                "employee_id": {"type": "string", "pattern": _ID_RX},
                "tanggal": {"type": "string", "pattern": _TGL_RX},
                "status": {"type": "string", "enum": list(STATUS_KOREKSI)},
                "jam_masuk": {"type": "string", "pattern": _JAM_RX},
                "jam_pulang": {"type": "string", "pattern": _JAM_RX},
                "catatan": {"type": "string", "maxLength": 200},
            }, "required": ["employee_id", "tanggal"], "additionalProperties": False}},
    }, "required": ["koreksi"], "additionalProperties": False},
    domain="sdm",
    risiko="menengah",
    menu="hr-attendance-hub",
)
class TerapkanKoreksiAbsen:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _tolak_gabungan(ctx)
        await ctx.api("GET", P_KOREKSI, params={"status": "pending", "limit": 1})   # 403 bila bukan SDM
        today = hari_ini(ctx).isoformat()
        ps = samaran(ctx)
        daftar, _ = await coba(ctx, "GET", "/api/hr/shifts/penugasan-karyawan")
        nama_by_id = {r.get("employee_id"): (r.get("name") or r.get("employee_code"))
                      for r in ((daftar or {}).get("data") or [])}
        perubahan, peringatan, terkunci, kunci = [], [], 0, set()
        for k in args.get("koreksi") or []:
            if not (k.get("status") or k.get("jam_masuk") or k.get("jam_pulang")):
                raise AlatError(400, f"Baris {k.get('tanggal')}: isi status, jam masuk, atau jam pulang yang benar.")
            if k["tanggal"] > today:
                raise AlatError(400, f"Tanggal {k['tanggal']} belum terjadi; koreksi hanya untuk hari ini atau sebelumnya.")
            if (k["employee_id"], k["tanggal"]) in kunci:
                raise AlatError(400, f"Ada dua baris untuk karyawan dan tanggal {k['tanggal']} yang sama; gabungkan.")
            kunci.add((k["employee_id"], k["tanggal"]))
            r = await _rekam(ctx, k["employee_id"], k["tanggal"])
            nama = nama_by_id.get(k["employee_id"]) or r.get("employee_name") or r.get("employee_code")
            if not nama:
                raise AlatError(404, f"Karyawan {k['employee_id']} tidak ditemukan atau sudah nonaktif.")
            if await _terkunci(ctx, k["employee_id"], k["tanggal"]):
                terkunci += 1
            perubahan.append({"label": f"{_nama_aman(ctx, ps, nama)} · {_tgl(k['tanggal'])}",
                              "sebelum": _ringkas_rekam(r), "sesudah": _ringkas_koreksi(k)})
        if terkunci:
            peringatan.append(f"{terkunci} tanggal sudah masuk gaji final: absensinya tidak diubah, selisihnya dibayar sebagai "
                              "penyesuaian di penggajian berikutnya.")
        n = len(perubahan)
        return {"judul": f"Koreksi absen ({n} baris)",
                "ringkas": f"{n} koreksi absen dibuat atas nama karyawan lalu langsung disetujui.",
                "perubahan": perubahan, "peringatan": peringatan,
                "catatan": ["Koreksi milik akun Anda sendiri tetap harus disetujui HR lain (pemisahan tugas).",
                            "Alasan yang Anda tulis disimpan sebagai alasan koreksi dan catatan persetujuan."]}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _tolak_gabungan(ctx)
        alasan = " ".join(str(getattr(ctx, "alasan", "") or "").split())[:400]
        if not alasan:
            raise AlatError(400, "Alasan koreksi wajib diisi saat menyetujui kartu ini.")
        hasil = {"langsung": 0, "penyesuaian_gaji": 0, "menunggu_hr_lain": 0, "gagal": []}
        for k in args.get("koreksi") or []:
            body = {"employee_id": k["employee_id"], "date": k["tanggal"],
                    "reason": f"Lewat Asisten AI: {alasan}" + (f" ({k['catatan']})" if k.get("catatan") else "")}
            if k.get("status"):
                body["status"] = k["status"]
            if k.get("jam_masuk"):
                body["clock_in"] = k["jam_masuk"]
            if k.get("jam_pulang"):
                body["clock_out"] = k["jam_pulang"]
            try:
                c = await ctx.api("POST", P_KOREKSI, json=body)
            except AlatError as e:
                hasil["gagal"].append({"tanggal": k["tanggal"], "employee_id": k["employee_id"], "pesan": e.pesan})
                continue
            try:
                out = await ctx.api("POST", f"{P_KOREKSI}/{c.get('id')}/approve", json={"note": alasan})
            except AlatError as e:
                if e.status == 403:
                    hasil["menunggu_hr_lain"] += 1
                else:
                    hasil["gagal"].append({"tanggal": k["tanggal"], "employee_id": k["employee_id"], "pesan": e.pesan})
                continue
            if ((out or {}).get("correction") or {}).get("apply_mode") == "penyesuaian_payroll":
                hasil["penyesuaian_gaji"] += 1
            else:
                hasil["langsung"] += 1
        bag = [f"{hasil['langsung']} absensi diperbarui"]
        if hasil["penyesuaian_gaji"]:
            bag.append(f"{hasil['penyesuaian_gaji']} menjadi penyesuaian gaji berikutnya (tanggal sudah final)")
        if hasil["menunggu_hr_lain"]:
            bag.append(f"{hasil['menunggu_hr_lain']} menunggu HR lain (koreksi milik Anda sendiri)")
        if hasil["gagal"]:
            bag.append(f"{len(hasil['gagal'])} gagal")
        return {"ringkas": "Koreksi absen: " + ", ".join(bag) + ".", "hasil": hasil, "pembatalan": None}


# ═══ Tindakan: susun draf shift ════════════════════════════════════════════════════════════════════════
CARA = ("pola", "shift", "berlaku", "salin")


async def _cari_pola(ctx, nilai: str) -> dict:
    d = (await ctx.api("GET", P_POLA)).get("data") or []
    v = str(nilai or "").strip().lower()
    for p in d:
        if p.get("id") == nilai or str(p.get("nama") or "").strip().lower() == v:
            return p
    cocok = [p for p in d if v and v in str(p.get("nama") or "").lower()]
    if len(cocok) == 1:
        return cocok[0]
    raise AlatError(404, f"Pola rotasi '{nilai}' tidak ditemukan. Pola yang ada: "
                         + (", ".join(p.get("nama") for p in d) or "belum ada (buat di Shift › Pola rotasi)") + ".")


async def _cari_shift(ctx, nilai: str) -> dict:
    d = (await ctx.api("GET", P_SHIFT, params={"include_default": False})).get("data") or []
    v = str(nilai or "").strip().upper()
    for s in d:
        if str(s.get("id")) == str(nilai) or str(s.get("shift_code") or "").upper() == v:
            return s
    raise AlatError(404, f"Shift '{nilai}' tidak ditemukan. Shift aktif: "
                         + (", ".join(str(s.get("shift_code")) for s in d) or "belum ada") + ".")


async def _isian_jadwal(ctx, args: dict) -> dict:
    cara = args.get("cara") or "pola"
    body: dict = {"start_date": args["mulai"], "end_date": args["selesai"], "cara": cara,
                  "isi_libur": bool(args.get("isi_libur"))}
    if args.get("departemen"):
        body["department"] = str(args["departemen"])[:80]
    if cara == "pola":
        if not args.get("pola"):
            raise AlatError(400, "Sebutkan pola rotasi yang dipakai (nama atau id).")
        p = await _cari_pola(ctx, args["pola"])
        body.update(pola_id=p["id"], mulai_pola=args.get("mulai_pola") or args["mulai"])
        body["_pola_nama"] = p.get("nama")
    elif cara == "shift":
        if not args.get("shift"):
            raise AlatError(400, "Sebutkan kode shift yang dipakai.")
        s = await _cari_shift(ctx, args["shift"])
        body["shift_id"] = str(s["id"])
        body["_shift_kode"] = s.get("shift_code")
    elif cara == "salin":
        if not args.get("salin_dari"):
            raise AlatError(400, "Sebutkan tanggal di minggu yang akan disalin (salin_dari).")
        body["salin_dari"] = args["salin_dari"]
    if args.get("judul"):
        body["judul"] = str(args["judul"])[:160]
    return body


@tindakan(
    name="susun_draf_shift",
    label="Menyusun draf jadwal shift",
    description=(
        "Susun DRAF jadwal shift (bukan terbit — belum dipakai absensi sampai SDM menerbitkannya di Shift › Roster) "
        "untuk rentang ≤ 62 hari, semua karyawan aktif atau satu departemen. Cara: `pola` (pola rotasi, sebut nama "
        "pola; hari pertama pola = `mulai_pola`), `shift` (satu kode shift; hari di luar hari kerja shift = libur), "
        "`berlaku` (salin shift yang berlaku sekarang), `salin` (ulang satu minggu sumber `salin_dari`). Hari cuti "
        "disetujui dilewati; hari libur kalender tidak dijadwalkan kecuali `isi_libur`. Kartu menampilkan cakupan per "
        "shift dan bentrok. Pakai `cakupan_shift` dulu untuk melihat pola, shift, dan cakupan yang ada."),
    input_schema={"type": "object", "properties": {
        "mulai": {"type": "string", "pattern": _TGL_RX},
        "selesai": {"type": "string", "pattern": _TGL_RX},
        "cara": {"type": "string", "enum": list(CARA)},
        "departemen": {"type": "string", "maxLength": 80},
        "pola": {"type": "string", "maxLength": 80, "description": "Nama atau id pola rotasi (cara=pola)."},
        "mulai_pola": {"type": "string", "pattern": _TGL_RX},
        "shift": {"type": "string", "maxLength": 40, "description": "Kode shift (cara=shift)."},
        "salin_dari": {"type": "string", "pattern": _TGL_RX},
        "isi_libur": {"type": "boolean"},
        "judul": {"type": "string", "maxLength": 160},
    }, "required": ["mulai", "selesai", "cara"], "additionalProperties": False},
    domain="sdm",
    risiko="rendah",
    menu="hr-shift-hub",
)
class SusunDrafShift:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        body = await _isian_jadwal(ctx, args)
        params = {k: v for k, v in body.items() if not k.startswith("_")}
        d = (await ctx.api("GET", P_PRATINJAU, params=params)).get("data") or {}
        meta, jb = d.get("metadata") or {}, d.get("jumlah_bentrok") or {}
        perubahan = [{"label": "Periode", "sebelum": "—", "sesudah": f"{_tgl(d.get('start_date'))} – {_tgl(d.get('end_date'))}"},
                     {"label": "Karyawan", "sebelum": "—", "sesudah": f"{d.get('karyawan')} orang"
                      + (f" ({body['department']})" if body.get("department") else "")}]
        perubahan += [{"label": f"Shift {p['kode']}", "sebelum": "—", "sesudah": f"{p['jumlah']} hari-orang"}
                      for p in meta.get("per_shift") or []]
        perubahan.append({"label": "Hari libur menurut jadwal", "sebelum": "—", "sesudah": f"{meta.get('hari_libur', 0)} hari-orang"})
        peringatan = []
        if d.get("dilewati"):
            peringatan.append(f"{len(d['dilewati'])} hari cuti disetujui dilewati (tidak dijadwalkan).")
        if jb.get("berat") or jb.get("peringatan"):
            peringatan.append(f"Bentrok: {jb.get('berat', 0)} berat, {jb.get('peringatan', 0)} peringatan — periksa di Roster "
                              "sebelum terbit.")
        asal = {"pola": f"pola {body.get('_pola_nama')}", "shift": f"shift {body.get('_shift_kode')}",
                "berlaku": "shift yang berlaku sekarang", "salin": f"salinan minggu {_tgl(body.get('salin_dari', ''))}"}
        return {"judul": "Draf jadwal shift",
                "ringkas": f"Draf jadwal dari {asal.get(body['cara'])}: {meta.get('total_shifts', 0)} hari-orang shift.",
                "perubahan": perubahan, "peringatan": peringatan,
                "catatan": ["Hasilnya DRAF: belum dipakai absensi sampai diterbitkan di Shift › Roster.",
                            "Draf bisa diubah per sel, disalin per minggu, atau dihapus di Roster."]}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        body = await _isian_jadwal(ctx, args)
        out = await ctx.api("POST", P_JADWAL, json={k: v for k, v in body.items() if not k.startswith("_")})
        j = (out or {}).get("data") or {}
        return {"ringkas": f"Draf jadwal dibuat ({j.get('judul') or 'tanpa judul'}). Buka Shift › Roster, pilih draf ini, "
                           "periksa, lalu terbitkan.",
                "hasil": {"jadwal_id": j.get("id"), "judul": j.get("judul"), "status": "draf",
                          "bentrok": j.get("jumlah_bentrok")},
                "pembatalan": {"jadwal_id": j.get("id")} if j.get("id") else None}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        jid = str((pembatalan or {}).get("jadwal_id") or "")
        if not re.match(_ID_RX, jid):
            raise AlatError(400, "Data pembatalan draf jadwal tidak lengkap.")
        try:
            await ctx.api("DELETE", f"{P_JADWAL}/{jid}")
        except AlatError as e:
            if e.status == 404:
                return {"ringkas": "Draf jadwal sudah tidak ada."}
            if e.status == 409:
                raise AlatError(409, "Jadwal ini sudah diterbitkan, jadi tidak dihapus otomatis. Tarik atau ubah di "
                                     "Shift › Roster.") from None
            raise
        return {"ringkas": "Draf jadwal dihapus."}

