"""Pembantu bersama alat baca agen laporan (keuangan, stok, produksi, sdm). Tidak mendaftarkan alat.

Isi: periode (bulan / rentang, pembanding periode sebelumnya), pembulatan uang, parameter CV, nama samaran
(K27), pembatas ukuran hasil (≤ 15 ribu karakter, Kontrak A).
"""
from __future__ import annotations

import calendar
import inspect
import json
import re
from datetime import date, timedelta
from typing import Any, Optional

from core.asisten_ai.alat_base import AlatError

BATAS_HASIL = 15000
_RX_BULAN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_RX_TANGGAL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
         "Oktober", "November", "Desember")

SKEMA_PERIODE = {
    "bulan": {"type": "string", "description": "Bulan TTTT-BB, mis. 2026-10. Kosong = bulan berjalan sampai hari ini."},
    "dari": {"type": "string", "description": "Awal rentang TTTT-BB-HH (dipakai bersama 'sampai', menggantikan 'bulan')."},
    "sampai": {"type": "string", "description": "Akhir rentang TTTT-BB-HH."},
}

# Peran yang boleh melihat total gaji dan nama karyawan asli (keputusan owner 1: gaji hanya SDM/owner).
PERAN_SDM_PENUH = ("owner", "superadmin", "hr", "hr_manager", "staff_hr")


def hari_ini(ctx) -> date:
    t = getattr(ctx, "today", None)
    if isinstance(t, date):
        return t
    if isinstance(t, str) and _RX_TANGGAL.match(t[:10]):
        return date.fromisoformat(t[:10])
    from utils.waktu import today_wib
    return today_wib()


def tanggal_sah(s: str, nama: str) -> date:
    if not isinstance(s, str) or not _RX_TANGGAL.match(s):
        raise AlatError(400, f"Tanggal '{nama}' harus berformat TTTT-BB-HH.")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise AlatError(400, f"Tanggal '{nama}' tidak valid.") from None


def label_tanggal(d: date) -> str:
    return f"{d.day} {BULAN[d.month - 1][:3]} {d.year}"


def label_rentang(a: date, b: date) -> str:
    if a.day == 1 and b == a.replace(day=calendar.monthrange(a.year, a.month)[1]):
        return f"{BULAN[a.month - 1]} {a.year}"
    return f"{label_tanggal(a)} – {label_tanggal(b)}"


def _mundur_bulan(d: date, n: int = 1) -> date:
    y, m = d.year, d.month - n
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def periode(args: dict, ctx) -> dict:
    """{dari, sampai, label, pembanding: {dari, sampai, label}} (tanggal ISO).

    * `bulan` lengkap (lampau) → bulan itu vs bulan sebelumnya (penuh);
    * `bulan` berjalan / kosong → tanggal 1 s.d. hari ini vs tanggal yang SAMA bulan lalu (adil);
    * `dari`+`sampai` → rentang itu vs rentang sepanjang itu tepat sebelumnya."""
    today = hari_ini(ctx)
    args = args or {}
    if args.get("dari") or args.get("sampai"):
        if not (args.get("dari") and args.get("sampai")):
            raise AlatError(400, "Isi 'dari' dan 'sampai' bersamaan (TTTT-BB-HH).")
        a, b = tanggal_sah(args["dari"], "dari"), tanggal_sah(args["sampai"], "sampai")
        if b < a:
            raise AlatError(400, "'sampai' tidak boleh sebelum 'dari'.")
        if (b - a).days > 731:
            raise AlatError(400, "Rentang paling panjang 2 tahun.")
        n = (b - a).days + 1
        pa, pb = a - timedelta(days=n), a - timedelta(days=1)
    else:
        bulan = args.get("bulan") or today.strftime("%Y-%m")
        if not isinstance(bulan, str) or not _RX_BULAN.match(bulan):
            raise AlatError(400, "Bulan harus berformat TTTT-BB, mis. 2026-10.")
        y, m = int(bulan[:4]), int(bulan[5:])
        a = date(y, m, 1)
        akhir = date(y, m, calendar.monthrange(y, m)[1])
        if a > today:
            raise AlatError(400, f"Bulan {bulan} belum dimulai.")
        if akhir >= today:          # bulan berjalan: sampai hari ini, pembanding hari yang sama bulan lalu
            b = today
            pa, pb = _mundur_bulan(a), _mundur_bulan(today)
        else:
            b = akhir
            pa = _mundur_bulan(a)
            pb = pa.replace(day=calendar.monthrange(pa.year, pa.month)[1])
    return {"dari": a.isoformat(), "sampai": b.isoformat(), "label": label_rentang(a, b),
            "pembanding": {"dari": pa.isoformat(), "sampai": pb.isoformat(), "label": label_rentang(pa, pb)}}


def rp(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def persen(a, b) -> Optional[float]:
    """a ÷ b × 100 (1 desimal); None bila b = 0."""
    try:
        return round(float(a) / float(b) * 100, 1) if float(b) else None
    except (TypeError, ValueError):
        return None


def perubahan(kini, lalu) -> dict:
    kini, lalu = float(kini or 0), float(lalu or 0)
    return {"selisih": rp(kini - lalu), "persen": persen(kini - lalu, abs(lalu)) if lalu else None}


def cv_aktif(ctx) -> str:
    cv = (getattr(ctx, "cv", None) or "DA").upper()
    return cv if cv in ("DA", "SMU", "ALL") else "DA"


def label_cv(cv: str) -> str:
    return {"DA": "CV Dewi Aditya", "SMU": "CV Sukma", "ALL": "Gabungan (CV Dewi Aditya + CV Sukma)"}.get(cv, cv)


def param_cv(ctx, cv: Optional[str] = None, **extra) -> dict:
    """Query `entity` dibaca `entity_from_request` SEBELUM header X-CV, jadi CV selalu eksplisit."""
    return {"entity": cv or cv_aktif(ctx), **{k: v for k, v in extra.items() if v not in (None, "")}}


def peran(ctx) -> str:
    return ((getattr(ctx, "user", None) or {}).get("role") or "").lower()


def boleh_sdm_penuh(ctx) -> bool:
    return peran(ctx) in PERAN_SDM_PENUH


# Akun/kategori yang isinya gaji (mis. "Gaji Pimpinan / Direksi" bisa = gaji satu orang). Untuk owner/SDM
# digabung menjadi SATU baris total; untuk peran lain tidak dirinci (keputusan owner 1, K27).
_RX_AKUN_GAJI = re.compile(r"gaji|upah|honor|tunjangan|thr|lembur|payroll|penggajian|pesangon|bpjs|insentif",
                           re.IGNORECASE)
LABEL_GAJI_GABUNGAN = "Gaji & tunjangan karyawan (gabungan)"
CATATAN_GAJI_DISEMBUNYIKAN = "Akun gaji/tunjangan tidak dirinci; hanya owner dan SDM yang melihat totalnya."


def akun_gaji(label) -> bool:
    return bool(_RX_AKUN_GAJI.search(str(label or "")))


def saring_akun_gaji(ctx, rows: list, kunci_label: str, kunci_nilai, *, kode: Optional[str] = None) -> tuple:
    """(baris tanpa akun gaji [+ satu baris gabungan untuk owner/SDM], catatan|None).

    `kunci_nilai` boleh satu kunci atau tuple kunci (semua dijumlah pada baris gabungan)."""
    kunci = (kunci_nilai,) if isinstance(kunci_nilai, str) else tuple(kunci_nilai)
    gaji = [r for r in rows if akun_gaji(r.get(kunci_label))]
    if not gaji:
        return rows, None
    sisa = [r for r in rows if not akun_gaji(r.get(kunci_label))]
    if not boleh_sdm_penuh(ctx):
        return sisa, CATATAN_GAJI_DISEMBUNYIKAN
    gabung = {kunci_label: LABEL_GAJI_GABUNGAN, "jumlah_akun": len(gaji)}
    if kode:
        gabung[kode] = "-"
    for k in kunci:
        gabung[k] = sum(float(r.get(k) or 0) for r in gaji)
    return sisa + [gabung], None


def samaran(ctx):
    """Pseudonymizer K27. Memakai milik inti (`ctx.samaran`) bila ada — supaya kode bisa dipetakan balik
    ke nama asli di server — kalau tidak, satu Pseudonymizer per panggilan alat (tanpa pemetaan balik)."""
    ps = getattr(ctx, "samaran", None)
    if ps is not None and callable(getattr(ps, "code", None)):
        return ps
    from services.ai.privacy import Pseudonymizer
    return Pseudonymizer()


async def saring_pii(ctx, obj):
    """`ctx.mask` (PII; dari services/ai/privacy) bila tersedia — sinkron atau async."""
    f = getattr(ctx, "mask", None)
    if not callable(f):
        return obj
    out = f(obj)
    return await out if inspect.isawaitable(out) else out


def ukuran(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def pangkas(hasil: dict, daftar_kunci: tuple = (), batas: int = BATAS_HASIL) -> dict:
    """Pastikan hasil ≤ batas karakter: daftar terpanjang dipotong bertahap (dan diberi tanda)."""
    if ukuran(hasil) <= batas:
        return hasil
    for _ in range(40):
        kandidat = []
        for k in daftar_kunci or tuple(hasil):
            v = hasil.get(k)
            if isinstance(v, list) and len(v) > 3:
                kandidat.append((ukuran(v), k))
        if not kandidat:
            break
        _, k = max(kandidat)
        hasil[k] = hasil[k][: max(3, int(len(hasil[k]) * 0.7))]
        hasil.setdefault("_dipangkas", [])
        if k not in hasil["_dipangkas"]:
            hasil["_dipangkas"].append(k)
        if ukuran(hasil) <= batas:
            break
    if "_dipangkas" in hasil:
        hasil["catatan_pangkas"] = ("Sebagian daftar dipotong agar ringkas: " + ", ".join(hasil.pop("_dipangkas"))
                                    + ". Minta rincian yang lebih sempit bila perlu.")
    return hasil


async def coba(ctx, method: str, path: str, params: Optional[dict] = None) -> tuple[Any, Optional[str]]:
    """Panggil endpoint; galat (mis. tidak punya akses) dikembalikan sebagai pesan, bukan dilempar.
    Dipakai untuk bagian TAMBAHAN suatu alat (bagian utama tetap melempar AlatError)."""
    try:
        return await ctx.api(method, path, params=params), None
    except AlatError as e:
        return None, e.pesan
