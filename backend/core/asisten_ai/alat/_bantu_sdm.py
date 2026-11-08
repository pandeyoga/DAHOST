"""Bantuan murni (tanpa I/O) alat SDM Asisten AI — audit HR Tahap D (9 Nov 2026). Modul berawalan `_` tidak dimuat
sebagai alat. Isi: deteksi ANOMALI payroll sebelum finalisasi (`anomali_payroll`) dan pengelompokan cakupan shift."""
from __future__ import annotations

from datetime import date
from typing import Optional

AMBANG_BRUTO_PERSEN = 20.0
AMBANG_PPH_PERSEN = 50.0
AMBANG_PPH_RUPIAH = 100_000
BATAS_LEMBUR_HARI = 4.0      # PP 35/2021: lembur hari kerja maks 4 jam/hari
BATAS_LEMBUR_MINGGU = 18.0   # dan 18 jam/minggu

JENIS_ANOMALI = {
    "gaji_minus": "Gaji bersih minus",
    "tanpa_absen": "Gaji dibayar tanpa satu pun catatan absen",
    "bonus_hangus_tanpa_catatan": "Bonus kehadiran hangus karena tidak ada catatan absen",
    "bruto_berubah": "Bruto berubah besar dibanding run sebelumnya",
    "pph21_lompat": "PPh21 naik/turun besar dibanding run sebelumnya",
    "lembur_lebih_4_jam": "Lembur lebih dari 4 jam di hari kerja",
    "lembur_lebih_18_jam_minggu": "Lembur lebih dari 18 jam dalam seminggu",
    "penyesuaian_manual": "Ada penyesuaian pendapatan manual",
    "peringatan_sistem": "Peringatan dari hitungan gaji",
}
URUT = list(JENIS_ANOMALI)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def pph21(slip: dict) -> float:
    return sum(_f(d.get("amount")) for d in slip.get("deductions") or [] if d.get("type") == "pph21")


def _persen(kini: float, lalu: float) -> Optional[float]:
    if not lalu:
        return None
    return round((kini - lalu) / lalu * 100, 1)


def anomali_payroll(slips: list, slips_lalu: Optional[list] = None, *, ambang_bruto: float = AMBANG_BRUTO_PERSEN,
                    ambang_pph: float = AMBANG_PPH_PERSEN) -> list:
    """[{jenis, label, employee_id, karyawan, departemen, pesan, nilai?}] urut jenis. `slips_lalu` = slip run final
    sebelumnya (pembanding bruto & PPh21). Deterministik — Asisten AI hanya menjelaskan."""
    lalu = {s.get("employee_id"): s for s in slips_lalu or []}
    out = []

    def tambah(jenis, s, pesan, **nilai):
        out.append({"jenis": jenis, "label": JENIS_ANOMALI[jenis], "employee_id": s.get("employee_id"),
                    "karyawan": s.get("employee_name") or s.get("employee_code") or s.get("employee_id"),
                    "departemen": s.get("department") or "", "pesan": pesan, **({"nilai": nilai} if nilai else {})})

    for s in slips or []:
        gross, net = _f(s.get("gross_pay")), _f(s.get("net_pay"))
        if net < 0:
            tambah("gaji_minus", s, f"Gaji bersih minus Rp {abs(round(net)):,}".replace(",", "."), neto=round(net))
        refs = s.get("source_refs") or {}
        ringkas = s.get("attendance_summary") or {}
        n_absen = refs.get("attendance_event_count")
        if s.get("pay_scheme") in ("monthly", "weekly") and gross > 0 and n_absen == 0:
            tambah("tanpa_absen", s, f"Tidak ada catatan absen di periode ini ({int(ringkas.get('tanpa_catatan') or 0)} "
                                     "hari kerja tanpa catatan); gaji tetap dibayar penuh.", bruto=round(gross))
        for al in s.get("allowances") or []:
            alasan = " ".join(str(x) for x in (al.get("forfeit_reasons") or []))
            if al.get("forfeited") and ("tidak ada hari hadir" in alasan.lower() or (n_absen == 0)):
                tambah("bonus_hangus_tanpa_catatan", s, f"{al.get('name') or 'Bonus kehadiran'} hangus ({alasan or 'tanpa hadir'}) "
                       "padahal hari kerja tanpa catatan bukan bukti mangkir.", tunjangan=round(_f(al.get("rate"))))
        p = lalu.get(s.get("employee_id"))
        if p:
            g0 = _f(p.get("gross_pay"))
            pct = _persen(gross, g0)
            if pct is not None and abs(pct) > ambang_bruto:
                tambah("bruto_berubah", s, f"Bruto {'naik' if pct > 0 else 'turun'} {abs(pct):g}% dari run sebelumnya "
                       f"(Rp {round(g0):,} → Rp {round(gross):,}).".replace(",", "."),
                       bruto=round(gross), bruto_lalu=round(g0), persen=pct)
            t0, t1 = pph21(p), pph21(s)
            pct_t = _persen(t1, t0)
            if (pct_t is not None and abs(pct_t) > ambang_pph and abs(t1 - t0) >= AMBANG_PPH_RUPIAH) or (not t0 and t1 >= AMBANG_PPH_RUPIAH * 5):
                tambah("pph21_lompat", s, f"PPh21 Rp {round(t0):,} → Rp {round(t1):,}.".replace(",", "."),
                       pph21=round(t1), pph21_lalu=round(t0))
        per_minggu: dict = {}
        for e in s.get("overtime_entries") or []:
            jam = _f(e.get("paid_hours") or e.get("hours"))
            if e.get("day_type") == "hari kerja" and jam > BATAS_LEMBUR_HARI:
                tambah("lembur_lebih_4_jam", s, f"{e.get('date')}: lembur {jam:g} jam di hari kerja (batas 4 jam).",
                       tanggal=e.get("date"), jam=jam)
            try:
                y, w, _ = date.fromisoformat(str(e.get("date"))[:10]).isocalendar()
                per_minggu[(y, w)] = per_minggu.get((y, w), 0.0) + jam
            except ValueError:
                pass
        for (y, w), jam in sorted(per_minggu.items()):
            if jam > BATAS_LEMBUR_MINGGU:
                tambah("lembur_lebih_18_jam_minggu", s, f"Minggu ke-{w} {y}: lembur {jam:g} jam (batas 18 jam).",
                       minggu=f"{y}-W{w:02d}", jam=jam)
        tambahan = _f(s.get("manual_addition"))
        if tambahan > 0:
            tambah("penyesuaian_manual", s, f"Penyesuaian pendapatan manual Rp {round(tambahan):,} — pastikan pajaknya "
                   "ikut dihitung.".replace(",", "."), tambahan=round(tambahan))
        for w in s.get("warnings") or []:
            if w.get("type") in ("negative_net",):
                continue
            tambah("peringatan_sistem", s, str(w.get("message") or w.get("type") or "Peringatan"))
    return sorted(out, key=lambda a: (URUT.index(a["jenis"]), str(a["karyawan"])))


def ringkas_anomali(anomali: list) -> list:
    hit: dict = {}
    for a in anomali:
        hit[a["jenis"]] = hit.get(a["jenis"], 0) + 1
    return [{"jenis": j, "label": JENIS_ANOMALI[j], "jumlah": hit[j]} for j in URUT if hit.get(j)]


def cakupan_roster(roster: dict) -> dict:
    """Dari jawaban `GET /api/hr/shift-scheduler/roster`: jumlah orang per tanggal per shift, per departemen, dan
    karyawan tanpa shift di hari kerja (bukan cuti/libur)."""
    shift = {s["id"]: s for s in roster.get("shift") or []}
    tanggal = [t["t"] for t in roster.get("tanggal") or []]
    libur = {t["t"]: t.get("libur") for t in roster.get("tanggal") or []}
    per_tgl = {t: {} for t in tanggal}
    per_dep: dict = {}
    kosong = []
    for k in roster.get("karyawan") or []:
        for c in k.get("sel") or []:
            s = shift.get(c.get("s")) if c.get("s") else None
            if s and not c.get("kunci"):
                per_tgl[c["t"]][s["kode"]] = per_tgl[c["t"]].get(s["kode"], 0) + 1
                d = per_dep.setdefault(k.get("departemen") or "Tanpa departemen", {})
                d[s["kode"]] = d.get(s["kode"], 0) + 1
            elif not s and not c.get("kunci") and not c.get("lj") and not libur.get(c["t"]):
                kosong.append({"employee_id": k["id"], "karyawan": k.get("nama"), "tanggal": c["t"]})
    return {"per_tanggal": [{"tanggal": t, "libur": libur.get(t), "per_shift": per_tgl[t],
                             "total": sum(per_tgl[t].values())} for t in tanggal],
            "per_departemen": [{"departemen": d, "per_shift": v, "total": sum(v.values())}
                               for d, v in sorted(per_dep.items())],
            "tanpa_shift": kosong}
