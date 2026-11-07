"""Alat umum Asisten AI: tanggal & batas periode (WIB) untuk tanggal relatif."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from core.asisten_ai.alat_base import AlatError, alat

_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")


def _bulan(y: int, m: int, today: date) -> dict:
    akhir = date(y, m, calendar.monthrange(y, m)[1])
    awal = date(y, m, 1)
    out = {"kode": f"{y:04d}-{m:02d}", "label": f"{_BULAN[m - 1]} {y}", "awal": awal.isoformat(),
           "akhir": akhir.isoformat(), "jumlah_hari": akhir.day}
    if awal <= today <= akhir:
        out["hari_berjalan"] = today.day
        out["sisa_hari"] = akhir.day - today.day
    return out


def _geser_bulan(y: int, m: int, n: int) -> tuple[int, int]:
    k = y * 12 + (m - 1) + n
    return k // 12, k % 12 + 1


def _minggu(senin: date) -> dict:
    return {"awal": senin.isoformat(), "akhir": (senin + timedelta(days=6)).isoformat()}


def _kuartal(y: int, q: int) -> dict:
    m1 = (q - 1) * 3 + 1
    akhir = date(y, m1 + 2, calendar.monthrange(y, m1 + 2)[1])
    return {"kode": f"{y}-Q{q}", "label": f"Kuartal {q} {y}", "awal": date(y, m1, 1).isoformat(),
            "akhir": akhir.isoformat()}


def susun_periode(today: date, periode: str | None = None) -> dict:
    y, m = today.year, today.month
    senin = today - timedelta(days=today.weekday())
    yl, ml = _geser_bulan(y, m, -1)
    q = (m - 1) // 3 + 1
    out = {
        "zona_waktu": "WIB (Asia/Jakarta)",
        "hari_ini": today.isoformat(),
        "hari": _HARI[today.weekday()],
        "kemarin": (today - timedelta(days=1)).isoformat(),
        "minggu_ini": _minggu(senin),
        "minggu_lalu": _minggu(senin - timedelta(days=7)),
        "bulan_ini": _bulan(y, m, today),
        "bulan_lalu": _bulan(yl, ml, today),
        "kuartal_ini": _kuartal(y, q),
        "tahun_ini": {"kode": str(y), "awal": date(y, 1, 1).isoformat(), "akhir": date(y, 12, 31).isoformat()},
        "catatan": "Minggu dihitung Senin–Minggu. Bulan berjalan belum lengkap; bandingkan dengan bulan lalu "
                   "pada hari yang sama (mis. tanggal 1–7) bila membandingkan bulan berjalan.",
    }
    if periode:
        try:
            py, pm = (int(x) for x in str(periode).split("-")[:2])
            if not 1 <= pm <= 12 or not 2000 <= py <= 2999:
                raise ValueError
        except ValueError:
            raise AlatError(400, "Periode harus berformat YYYY-MM, mis. 2026-10.")
        out["periode_diminta"] = _bulan(py, pm, today)
    return out


@alat(
    name="tanggal_dan_periode",
    kind="read",
    label="Memeriksa tanggal dan periode",
    description=(
        "Mengembalikan tanggal hari ini menurut WIB, nama hari, kemarin, batas minggu ini dan minggu lalu "
        "(Senin–Minggu), bulan ini (kode YYYY-MM, label, tanggal awal/akhir, hari berjalan), bulan lalu, "
        "kuartal ini, dan tahun ini. Panggil sebelum memakai tanggal relatif ('kemarin', 'minggu lalu', "
        "'bulan lalu', 'kuartal ini') di alat lain supaya batas tanggalnya pasti. Isian opsional `periode` "
        "(YYYY-MM) mengembalikan juga batas bulan tersebut."
    ),
    input_schema={
        "type": "object",
        "properties": {"periode": {"type": "string", "pattern": r"^\d{4}-\d{2}$",
                                   "description": "Opsional: bulan YYYY-MM yang ingin diketahui batasnya."}},
        "additionalProperties": False,
    },
    domain="umum",
)
async def tanggal_dan_periode(ctx, args: dict) -> dict:
    return susun_periode(ctx.today, (args or {}).get("periode"))
