"""Alat baca Asisten AI — SDM ringkas (Kontrak A). Angka dari endpoint SDM lewat `ctx.api`.

Aturan privasi (keputusan owner 1 + K27):
  * gaji PER ORANG tidak pernah dikembalikan; TOTAL penggajian hanya untuk owner/superadmin/SDM;
  * nama karyawan asli hanya untuk owner/superadmin/SDM — peran lain mendapat kode samaran KRY-xxx dan hasil
    akhirnya dilewatkan `ctx.mask`;
  * hak baca data karyawan lain tetap dijaga endpoint (laporan SDM: peran SDM/manajer; cuti: SDM/atasan).
Sumber: `GET /api/rahaza/hr/dashboard`, `GET /api/rahaza/hr/reports/{attendance,overtime,payroll}-summary`,
`GET /api/rahaza/hr/reports/turnover`, `GET /api/rahaza/leaves`, `GET /api/rahaza/leave-types`.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat
from core.asisten_ai.alat._bantu_laporan import (
    SKEMA_PERIODE, boleh_sdm_penuh, coba, hari_ini, pangkas, periode, persen, rp, samaran, saring_pii,
)

P_DASBOR = "/api/rahaza/hr/dashboard"
P_ABSENSI = "/api/rahaza/hr/reports/attendance-summary"
P_LEMBUR = "/api/rahaza/hr/reports/overtime-summary"
P_GAJI = "/api/rahaza/hr/reports/payroll-summary"
P_PERGANTIAN = "/api/rahaza/hr/reports/turnover"
P_CUTI = "/api/rahaza/leaves"
P_JENIS_CUTI = "/api/rahaza/leave-types"

LABEL_STATUS_CUTI = {"draft": "Draf", "pending_approval": "Menunggu atasan", "pending_hr_approval": "Menunggu SDM",
                     "approved": "Disetujui", "rejected": "Ditolak", "cancelled": "Dibatalkan"}


def _nama(ctx, ps, nama):
    if not nama:
        return None
    return nama if boleh_sdm_penuh(ctx) else ps.code(nama, "karyawan")


async def _akhiri(ctx, hasil: dict, daftar=()) -> dict:
    if not boleh_sdm_penuh(ctx):
        hasil["catatan_nama"] = "Nama karyawan disamarkan (kode KRY-xxx) sesuai hak akses Anda."
        hasil = await saring_pii(ctx, hasil)
    return pangkas(hasil, daftar)


@alat(
    name="jumlah_karyawan",
    kind="read",
    label="Membaca jumlah karyawan",
    description=(
        "Jumlah karyawan aktif, sebaran per departemen, kehadiran hari ini (hadir/izin/sakit/cuti/alfa/belum "
        "absen), alfa 7 hari terakhir, karyawan masuk & keluar dalam periode (bila punya akses laporan SDM), dan "
        "— hanya untuk owner/superadmin/SDM — total biaya penggajian terakhir yang final (bruto, potongan, neto; "
        "tanpa rincian per orang)."),
    input_schema={"type": "object", "properties": dict(SKEMA_PERIODE), "additionalProperties": False},
    domain="sdm",
)
async def jumlah_karyawan(ctx, args: dict) -> dict:
    d = await ctx.api("GET", P_DASBOR)
    total = int(d.get("total_employees") or 0)
    hari = d.get("attendance_today") or {}
    hasil = {
        "per_tanggal": hari_ini(ctx).isoformat(),
        "karyawan_aktif": total,
        "per_departemen": [{"departemen": r.get("dept") or "Tanpa departemen", "jumlah": r.get("count"),
                            "porsi_pct": persen(r.get("count"), total)} for r in d.get("dept_breakdown") or []],
        "kehadiran_hari_ini": {k: hari.get(k) for k in ("hadir", "izin", "sakit", "cuti", "alfa", "not_recorded",
                                                        "attendance_rate") if k in hari},
        "alfa_7_hari": d.get("alfa_last_7d"),
    }
    if "not_recorded" in hasil["kehadiran_hari_ini"]:
        hasil["kehadiran_hari_ini"]["belum_absen"] = hasil["kehadiran_hari_ini"].pop("not_recorded")
    if "attendance_rate" in hasil["kehadiran_hari_ini"]:
        hasil["kehadiran_hari_ini"]["persen_hadir"] = hasil["kehadiran_hari_ini"].pop("attendance_rate")
    p = periode(args, ctx)
    pg, _ = await coba(ctx, "GET", P_PERGANTIAN, {"from_date": p["dari"], "to_date": p["sampai"]})
    if pg:
        a = pg.get("aggregates") or {}
        hasil["pergantian"] = {"periode": p["label"], "masuk": a.get("new_hires_count"),
                               "keluar": a.get("resignations_count"), "tingkat_keluar_pct": a.get("turnover_rate")}
    if boleh_sdm_penuh(ctx):
        gaji, galat = await coba(ctx, "GET", P_GAJI)
        if gaji and not (gaji.get("period") or {}).get("run_id"):
            hasil["biaya_tenaga_kerja_terakhir"] = {"catatan": "Belum ada penggajian yang sudah final."}
        elif gaji:
            a = gaji.get("aggregates") or {}
            # Total saja (keputusan owner 1). Daftar per karyawan (`summary`) sengaja tidak dibaca.
            hasil["biaya_tenaga_kerja_terakhir"] = {
                "periode": (gaji.get("period") or {}).get("period_code"), "karyawan_dibayar": a.get("total_employees"),
                "bruto": rp(a.get("total_gross")), "potongan": rp(a.get("total_deductions")),
                "neto": rp(a.get("total_net"))}
        elif galat:
            hasil["biaya_tenaga_kerja_terakhir"] = {"galat": galat}
    hasil["_sumber"] = "Dasbor SDM"
    return await _akhiri(ctx, hasil)


@alat(
    name="ringkasan_absensi",
    kind="read",
    label="Membaca ringkasan absensi",
    description=(
        "Rekap absensi karyawan aktif untuk satu bulan (bawaan bulan berjalan s.d. hari ini) atau rentang: hari "
        "kerja, total hadir/izin/sakit/cuti/alfa/terlambat, rata-rata persen kehadiran (hadir ÷ hari kerja), rekap "
        "per departemen, 5 karyawan dengan alfa terbanyak, dan tren harian hadir/alfa. Butuh akses laporan SDM. "
        "Nama hanya tampil untuk owner/SDM; lainnya kode KRY-xxx."),
    input_schema={"type": "object", "properties": {
        **SKEMA_PERIODE, "departemen": {"type": "string", "description": "Nama departemen (opsional)."},
    }, "additionalProperties": False},
    domain="sdm",
)
async def ringkasan_absensi(ctx, args: dict) -> dict:
    p = periode(args, ctx)
    params = {"from_date": p["dari"], "to_date": p["sampai"]}
    if (args or {}).get("departemen"):
        params["department_id"] = str(args["departemen"])[:80]
    d = await ctx.api("GET", P_ABSENSI, params=params)
    a = d.get("aggregates") or {}
    rows = d.get("summary") or []
    ps = samaran(ctx)
    per_dep: dict = {}
    for r in rows:
        dep = r.get("department_name") or "Tanpa departemen"
        s = per_dep.setdefault(dep, {"departemen": dep, "karyawan": 0, "alfa": 0, "terlambat": 0, "_rate": 0.0})
        s["karyawan"] += 1
        s["alfa"] += int(r.get("alfa") or r.get("alpha") or 0)
        s["terlambat"] += int(r.get("late") or r.get("terlambat") or 0)
        s["_rate"] += float(r.get("attendance_rate") or 0)
    for s in per_dep.values():
        s["persen_hadir_rata"] = round(s.pop("_rate") / s["karyawan"], 1) if s["karyawan"] else None
    alfa_top = sorted((r for r in rows if int(r.get("alfa") or r.get("alpha") or 0) > 0),
                      key=lambda r: -int(r.get("alfa") or r.get("alpha") or 0))[:5]
    hasil = {
        "periode": p["label"], "dari": p["dari"], "sampai": p["sampai"],
        "ringkas": {"karyawan": a.get("total_employees"), "hari_kerja": a.get("working_days"),
                    "hadir": a.get("total_hadir"), "izin": a.get("total_izin"), "sakit": a.get("total_sakit"),
                    "cuti": a.get("total_cuti"), "alfa": a.get("total_alfa"), "terlambat": a.get("total_terlambat"),
                    "persen_hadir_rata": a.get("avg_attendance_rate")},
        "per_departemen": sorted(per_dep.values(), key=lambda s: -s["karyawan"])[:15],
        "alfa_terbanyak": [{"karyawan": _nama(ctx, ps, r.get("employee_name")),
                            "departemen": r.get("department_name"), "alfa": int(r.get("alfa") or r.get("alpha") or 0),
                            "persen_hadir": r.get("attendance_rate")} for r in alfa_top],
        "tren_harian": [{"tanggal": c.get("date"), "hadir": c.get("hadir"), "alfa": c.get("alfa")}
                        for c in (d.get("chart_data") or [])[:31]],
        "_sumber": "Laporan absensi SDM",
    }
    return await _akhiri(ctx, hasil, ("tren_harian", "per_departemen"))


@alat(
    name="cuti_dan_lembur",
    kind="read",
    label="Membaca cuti dan lembur",
    description=(
        "Rekap cuti dan lembur untuk satu bulan (bawaan bulan berjalan) atau rentang: pengajuan cuti per status "
        "dan per jenis cuti beserta jumlah hari disetujui dan yang menunggu persetujuan; lembur total jam, jumlah "
        "karyawan lembur, rata-rata jam per karyawan, per departemen, dan 5 karyawan dengan jam lembur terbanyak. "
        "Tanpa akses SDM, cuti hanya milik sendiri dan lembur tidak terbaca. Nama hanya untuk owner/SDM."),
    input_schema={"type": "object", "properties": dict(SKEMA_PERIODE), "additionalProperties": False},
    domain="sdm",
)
async def cuti_dan_lembur(ctx, args: dict) -> dict:
    p = periode(args, ctx)
    ps = samaran(ctx)
    cuti = await ctx.api("GET", P_CUTI, params={"date_from": p["dari"], "date_to": p["sampai"], "limit": 500})
    items = (cuti or {}).get("items") or []
    jenis_map = {}
    jenis, _ = await coba(ctx, "GET", P_JENIS_CUTI)
    for j in jenis if isinstance(jenis, list) else []:
        jenis_map[j.get("id")] = j.get("name") or j.get("code")
    per_status: dict = {}
    per_jenis: dict = {}
    for r in items:
        st = LABEL_STATUS_CUTI.get(r.get("status"), r.get("status") or "-")
        per_status[st] = per_status.get(st, 0) + 1
        nama_j = r.get("leave_type_name") or jenis_map.get(r.get("leave_type_id")) or "Lainnya"
        s = per_jenis.setdefault(nama_j, {"jenis": nama_j, "pengajuan": 0, "hari_disetujui": 0})
        s["pengajuan"] += 1
        if r.get("status") == "approved":
            s["hari_disetujui"] += float(r.get("duration_days") or 0)
    hasil = {
        "periode": p["label"], "dari": p["dari"], "sampai": p["sampai"],
        "cuti": {"jumlah_pengajuan": int((cuti or {}).get("total") or len(items)),
                 "per_status": per_status,
                 "per_jenis": sorted(per_jenis.values(), key=lambda s: -s["pengajuan"]),
                 "total_hari_disetujui": sum(s["hari_disetujui"] for s in per_jenis.values()),
                 "menunggu_persetujuan": sum(1 for r in items if r.get("status") in ("pending_approval",
                                                                                     "pending_hr_approval"))},
    }
    if (cuti or {}).get("has_more"):
        hasil["cuti"]["catatan"] = "Lebih dari 500 pengajuan; rincian per jenis dihitung dari 500 terbaru."
    lembur, galat = await coba(ctx, "GET", P_LEMBUR, {"from_date": p["dari"], "to_date": p["sampai"]})
    if lembur:
        a = lembur.get("aggregates") or {}
        rows = lembur.get("summary") or []
        per_dep: dict = {}
        for r in rows:
            dep = r.get("department_name") or "Tanpa departemen"
            per_dep[dep] = round(per_dep.get(dep, 0) + float(r.get("total_ot_hours") or 0), 2)
        hasil["lembur"] = {
            "total_jam": round(float(a.get("total_ot_hours") or 0), 1),
            "karyawan_lembur": a.get("total_employees_with_ot"),
            "rata_jam_per_karyawan": a.get("avg_ot_per_emp"),
            "per_departemen": [{"departemen": k, "jam": v} for k, v in sorted(per_dep.items(), key=lambda kv: -kv[1])][:12],
            "jam_terbanyak": [{"karyawan": _nama(ctx, ps, r.get("employee_name")), "departemen": r.get("department_name"),
                               "jam": round(float(r.get("total_ot_hours") or 0), 1), "hari": r.get("ot_days")}
                              for r in sorted(rows, key=lambda r: -float(r.get("total_ot_hours") or 0))[:5]],
        }
    elif galat:
        hasil["lembur"] = {"galat": galat}
    from utils.employee_identity import can_view_all_employees
    if not can_view_all_employees(getattr(ctx, "user", None) or {}):
        hasil["catatan_akses"] = "Tanpa akses SDM, data cuti yang terbaca hanya pengajuan milik Anda sendiri."
    hasil["_sumber"] = "Cuti & lembur (SDM)"
    return await _akhiri(ctx, hasil)
