"""Alat Asisten AI — DATA SAYA (audit HR Tahap D, 9 Nov 2026). Ruang `saya` (Portal Saya › Tanya Asisten).

Semua alat hanya memanggil endpoint swalayan Portal Saya dengan token pengguna, jadi yang terbaca SELALU data
milik akun itu sendiri (endpoint mencari karyawan dari akun yang login; tidak ada isian id karyawan):
  absen_saya        `GET /api/rahaza/self/attendance` + `GET /api/rahaza/attendance/corrections/my`
  cuti_saya         `GET /api/portal-saya/me/leave-balance` + `GET /api/portal-saya/me/leaves`
  slip_gaji_saya    `GET /api/portal-saya/me/payslips` (hanya slip run final/dibayar)
  jadwal_shift_saya `GET /api/portal/shift/jadwal-saya` + `GET /api/portal/shift/permintaan`
Gaji milik sendiri BOLEH ditampilkan ke pemiliknya (`ctx.mask(gaji=True)`); data pribadi lain tetap disamarkan.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat
from core.asisten_ai.alat._bantu_laporan import SKEMA_PERIODE, coba, pangkas, periode, rp

P_ABSEN = "/api/rahaza/self/attendance"
P_KOREKSI = "/api/rahaza/attendance/corrections/my"
P_SALDO = "/api/portal-saya/me/leave-balance"
P_CUTI = "/api/portal-saya/me/leaves"
P_SLIP = "/api/portal-saya/me/payslips"
P_JADWAL = "/api/portal/shift/jadwal-saya"
P_MINTA = "/api/portal/shift/permintaan"

STATUS_CUTI = {"draft": "Draf", "pending_approval": "Menunggu atasan", "pending_hr_approval": "Menunggu SDM",
               "approved": "Disetujui", "rejected": "Ditolak", "cancelled": "Dibatalkan"}
STATUS_KOREKSI = {"pending": "Menunggu SDM", "approved": "Disetujui", "rejected": "Ditolak", "cancelled": "Dibatalkan"}


def _milik_sendiri(ctx, hasil: dict) -> dict:
    """Samarkan data pribadi (HP, alamat, NIK…) tetapi gaji MILIK SENDIRI tetap tampil."""
    m = getattr(ctx, "mask", None)
    return m(hasil, gaji=True) if callable(m) else hasil


def _jam(v) -> str:
    from core.absensi_pengecualian import jam_lokal
    return jam_lokal(v) or "—"


@alat(
    name="absen_saya",
    kind="read",
    label="Membaca absen saya",
    description=(
        "Absensi MILIK pengguna sendiri untuk satu bulan (bawaan bulan berjalan) atau rentang: rekap hadir/izin/sakit/cuti/"
        "alpa/libur, total jam kerja, total menit terlambat, daftar per hari (status, jam masuk/pulang WIB, terlambat, "
        "lembur), dan status pengajuan koreksi absen. Untuk mengajukan koreksi arahkan ke Portal Saya › Absen Saya."),
    input_schema={"type": "object", "properties": dict(SKEMA_PERIODE), "additionalProperties": False},
    domain="saya",
)
async def absen_saya(ctx, args: dict) -> dict:
    p = periode(args, ctx)
    d = await ctx.api("GET", P_ABSEN, params={"from": p["dari"], "to": p["sampai"], "limit": 400})
    rows = sorted(d.get("records") or [], key=lambda r: str(r.get("date")))
    kor, _ = await coba(ctx, "GET", P_KOREKSI, {"limit": 20})
    hasil = {
        "periode": p["label"], "dari": p["dari"], "sampai": p["sampai"],
        "rekap": {**(d.get("summary") or {}), "jam_kerja": d.get("total_hours_worked"),
                  "menit_terlambat": sum(int(r.get("late_minutes") or 0) for r in rows),
                  "hari_terlambat": sum(1 for r in rows if int(r.get("late_minutes") or 0) > 0)},
        "per_hari": [{"tanggal": r.get("date"), "status": r.get("status") or "hadir", "masuk": _jam(r.get("clock_in")),
                      "pulang": _jam(r.get("clock_out")), "terlambat_menit": int(r.get("late_minutes") or 0),
                      "lembur_jam": r.get("overtime_hours") or 0, "shift": r.get("shift_code")} for r in rows],
        "koreksi_absen": [{"tanggal": c.get("date"), "status": STATUS_KOREKSI.get(c.get("status"), c.get("status")),
                           "alasan": c.get("reason")} for c in ((kor or {}).get("items") or [])[:10]],
        "catatan": "Hari kerja tanpa catatan absen tidak memotong gaji, tetapi sebaiknya dilengkapi lewat koreksi absen.",
        "_sumber": "Absen Saya",
    }
    return pangkas(_milik_sendiri(ctx, hasil), ("per_hari",))


@alat(
    name="cuti_saya",
    kind="read",
    label="Membaca cuti saya",
    description=(
        "Saldo cuti MILIK pengguna sendiri tahun berjalan (jatah, terpakai, sisa per jenis) dan pengajuan cuti/izin/sakit "
        "terakhir beserta statusnya (menunggu atasan/SDM, disetujui, ditolak, dibatalkan). Untuk mengajukan, arahkan ke "
        "Portal Saya › Cuti & Lembur."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    domain="saya",
)
async def cuti_saya(ctx, args: dict) -> dict:
    saldo = await ctx.api("GET", P_SALDO)
    aju, _ = await coba(ctx, "GET", P_CUTI, {"limit": 30})
    hasil = {
        "tahun": saldo.get("year"),
        "saldo": [{"jenis": b.get("leave_type_name") or b.get("name") or b.get("leave_type_code"),
                   "jatah": b.get("quota", b.get("allocated")), "terpakai": b.get("used"),
                   "sisa": b.get("remaining")} for b in saldo.get("balances") or []],
        "pengajuan": [{"dari": r.get("from_date"), "sampai": r.get("to_date"), "hari": r.get("duration_days"),
                       "jenis": r.get("leave_type_name") or r.get("request_type"), "status": STATUS_CUTI.get(r.get("status"), r.get("status")),
                       "setengah_hari": bool(r.get("is_half_day")), "alasan": r.get("reason")}
                      for r in ((aju or {}).get("items") or [])[:20]],
        "_sumber": "Cuti & Lembur (Portal Saya)",
    }
    return pangkas(_milik_sendiri(ctx, hasil), ("pengajuan",))


@alat(
    name="slip_gaji_saya",
    kind="read",
    label="Membaca slip gaji saya",
    description=(
        "Slip gaji MILIK pengguna sendiri (hanya penggajian yang sudah final): daftar periode dengan bruto, potongan, dan "
        "gaji bersih, plus rincian satu slip (bawaan terbaru; atau `bulan` TTTT-BB = bulan akhir periode): pendapatan, "
        "tunjangan (termasuk alasan bonus hangus), lembur, potongan (terlambat, tidak masuk, BPJS, PPh21, kasbon), dan "
        "catatan hitungan. Gaji orang lain tidak pernah terbaca."),
    input_schema={"type": "object", "properties": {
        "bulan": {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$", "description": "Bulan akhir periode, mis. 2026-10."},
    }, "additionalProperties": False},
    domain="saya",
)
async def slip_gaji_saya(ctx, args: dict) -> dict:
    d = await ctx.api("GET", P_SLIP, params={"limit": 12})
    slips = d.get("payslips") or []
    if not slips:
        return {"catatan": "Belum ada slip gaji final untuk akun ini.", "_sumber": "Slip Gaji"}
    bulan = (args or {}).get("bulan")
    pilih = next((s for s in slips if str(s.get("period_to") or "")[:7] == bulan), None) if bulan else slips[0]
    hasil = {
        "daftar": [{"periode": f"{s.get('period_from')} s.d. {s.get('period_to')}", "bruto": rp(s.get("gross_pay")),
                    "potongan": rp(s.get("deductions_total")), "bersih": rp(s.get("net_pay"))} for s in slips],
    }
    if bulan and not pilih:
        hasil["catatan"] = f"Tidak ada slip final dengan periode berakhir di {bulan}."
    if pilih:
        hasil["rincian"] = {
            "periode": f"{pilih.get('period_from')} s.d. {pilih.get('period_to')}",
            "pendapatan": [{"keterangan": e.get("label"), "jumlah": rp(e.get("amount"))} for e in pilih.get("earnings") or []],
            "tunjangan": [{"keterangan": a.get("label") or a.get("name"), "jumlah": rp(a.get("amount")),
                           "hangus": bool(a.get("forfeited")), "alasan_hangus": a.get("forfeit_reasons") or []}
                          for a in pilih.get("allowances") or []],
            "lembur": {"jam": pilih.get("overtime_hours"), "jumlah": rp(pilih.get("overtime_amount"))},
            "potongan": [{"keterangan": x.get("label"), "jumlah": rp(x.get("amount"))} for x in pilih.get("deductions") or []],
            "bruto": rp(pilih.get("gross_pay")), "total_potongan": rp(pilih.get("deductions_total")),
            "bersih": rp(pilih.get("net_pay")),
            "kehadiran": pilih.get("attendance_summary") or {},
            "catatan_hitungan": [w.get("message") for w in pilih.get("warnings") or [] if w.get("message")],
        }
    hasil["_sumber"] = "Slip Gaji"
    return pangkas(_milik_sendiri(ctx, hasil), ("daftar",))


@alat(
    name="jadwal_shift_saya",
    kind="read",
    label="Membaca jadwal shift saya",
    description=(
        "Shift MILIK pengguna sendiri per hari mulai hari ini (bawaan 14 hari, paling banyak 42): kode & jam shift, hari "
        "libur/cuti, dan status permintaan ganti/tukar shift (termasuk ajakan tukar dari rekan). Untuk mengajukan, arahkan "
        "ke Portal Saya › Jadwal Shift."),
    input_schema={"type": "object", "properties": {
        "hari": {"type": "integer", "minimum": 1, "maximum": 42},
    }, "additionalProperties": False},
    domain="saya",
)
async def jadwal_shift_saya(ctx, args: dict) -> dict:
    d = await ctx.api("GET", P_JADWAL, params={"hari": int((args or {}).get("hari") or 14)})
    m, _ = await coba(ctx, "GET", P_MINTA)
    m = m or {}
    hasil = {
        "hari": [{"tanggal": h.get("date"), "label": h.get("label"),
                  "shift": (f"{h['shift']['kode']} {h['shift']['mulai']}–{h['shift']['selesai']}" if h.get("shift") else None),
                  "keterangan": h.get("keterangan")} for h in d.get("hari") or []],
        "permintaan_saya": [{"tanggal": r.get("tanggal"), "jenis": r.get("label_jenis"), "status": r.get("label_status")}
                            for r in (m.get("milik_saya") or [])[:10]],
        "ajakan_tukar": [{"tanggal": r.get("tanggal"), "dari": r.get("employee_name"), "status": r.get("label_status")}
                         for r in (m.get("sebagai_rekan") or []) if r.get("status") == "menunggu_rekan"],
        "_sumber": "Jadwal Shift (Portal Saya)",
    }
    return pangkas(_milik_sendiri(ctx, hasil), ("hari",))
