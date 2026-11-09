"""core.laporan_marketing — **Laporan Marketing mode AI: paket fakta + penjaga angka** (audit Marketing §6.4).

Prinsip: ANGKA DIHITUNG KODE, AI HANYA MEMBACA & MENAFSIR.

1. :func:`paket_fakta` — satu JSON berversi berisi semua angka laporan mingguan/bulanan, dihitung
   dari pembaca RESMI (`core.ukuran_penjualan`: penjualan per toko/platform/kanal/hari, produk
   teratas & terbawah, target, iklan per toko & kampanye, live, setoran/biaya platform) +
   komplain. Pembanding: periode sebelumnya (panjang sama) dan — untuk bulanan — tahun lalu.
   Ditambah KPI turunan (AOV, % batal, % retur, TACoS, ROAS, biaya platform %), ANOMALI (hari di
   luar ±2σ, toko tanpa data, lonjakan batal, kampanye rugi, selisih rekap vs setoran), dan
   KUALITAS DATA (hari berdata per toko, iklan/setoran belum diimpor). Disimpan dengan id
   (`ai_fakta_laporan_marketing`) supaya penjaga angka bisa memeriksa laporan AI.
2. :func:`periksa_angka` — penjaga anti-halusinasi: setiap angka rupiah/persen di narasi & tabel
   laporan AI WAJIB ada di paket fakta (toleransi pembulatan tampilan). Angka asing ⇒ laporan
   ditolak dan AI diminta memperbaiki (alat `buat_laporan_marketing`).
3. :func:`mulai_percakapan` — membuka percakapan Asisten AI (mesin yang sama dengan chat:
   gerbang kunci/anggaran/log biaya) yang langsung menjalankan permintaan laporan.
"""
from __future__ import annotations

import calendar
import math
import re
import statistics
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import ukuran_penjualan as U

VERSI = "laporan-marketing-1"
KOLEKSI_FAKTA = "ai_fakta_laporan_marketing"
SIGMA = 2.0
JENIS = ("mingguan", "bulanan", "rentang")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")


class GalatLaporan(ValueError):
    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = int(status)
        self.pesan = str(pesan)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PERIODE
# ═══════════════════════════════════════════════════════════════════════════════
def periode_laporan(jenis: str, hari_ini: date, dari: Optional[str] = None,
                    sampai: Optional[str] = None) -> Tuple[str, str, str]:
    """(dari, sampai, label). Bawaan: pekan lalu Senin–Minggu / bulan lalu penuh."""
    if dari or sampai:
        a = date.fromisoformat((dari or sampai)[:10])
        b = date.fromisoformat((sampai or dari)[:10])
        if b < a:
            raise GalatLaporan(400, "Tanggal akhir tidak boleh sebelum tanggal awal.")
        if (b - a).days > 92:
            raise GalatLaporan(400, "Rentang laporan paling panjang 93 hari.")
        return a.isoformat(), b.isoformat(), _label(a, b)
    if jenis == "bulanan":
        akhir = hari_ini.replace(day=1) - timedelta(days=1)
        a = akhir.replace(day=1)
        return a.isoformat(), akhir.isoformat(), f"{_BULAN[a.month - 1]} {a.year}"
    senin = hari_ini - timedelta(days=hari_ini.weekday()) - timedelta(days=7)
    minggu = senin + timedelta(days=6)
    return senin.isoformat(), minggu.isoformat(), _label(senin, minggu)


def _label(a: date, b: date) -> str:
    if a.day == 1 and b == a.replace(day=calendar.monthrange(a.year, a.month)[1]):
        return f"{_BULAN[a.month - 1]} {a.year}"
    return f"{a.day} {_BULAN[a.month - 1][:3]} {a.year} – {b.day} {_BULAN[b.month - 1][:3]} {b.year}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PAKET FAKTA
# ═══════════════════════════════════════════════════════════════════════════════
def _p(a: float, b: float, nd: int = 1) -> Optional[float]:
    try:
        return round(float(a) / float(b) * 100, nd) if float(b) else None
    except (TypeError, ValueError):
        return None


def _rp(v: Any) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _ringkas_baris(rows: Sequence[dict], keys: Sequence[str], n: int) -> List[dict]:
    out = []
    for r in list(rows)[:n]:
        out.append({k: r.get(k) for k in keys if k in r})
    return out


async def _komplain(db, ids: Sequence[str], dari: str, sampai: str) -> dict:
    if not ids:
        return {"jumlah": 0, "per_kategori": {}}
    q = {"$and": [{"account_id": {"$in": list(ids)}}, U.filter_tanggal("complaint_date", dari, sampai),
                  dict(U.TANPA_CONTOH)]}
    per: Dict[str, int] = {}
    n = 0
    async for c in db.marketing_complaints.find(q, {"_id": 0, "category": 1, "complaint_date": 1}):
        k = U.kunci_tanggal(c.get("complaint_date"))
        if k is None or not (dari <= k <= sampai):
            continue
        n += 1
        per[str(c.get("category") or "lainnya")] = per.get(str(c.get("category") or "lainnya"), 0) + 1
    return {"jumlah": n, "per_kategori": dict(sorted(per.items(), key=lambda kv: -kv[1]))}


async def paket_fakta(db, accounts: Sequence[dict], *, jenis: str, dari: str, sampai: str, label: str,
                      cv: str = "DA") -> dict:
    """Semua angka laporan Marketing untuk ``accounts`` (sudah berlingkup pengguna) pada rentang itu."""
    if jenis not in JENIS:
        raise GalatLaporan(400, "Jenis laporan harus mingguan, bulanan, atau rentang.")
    ids = [a["id"] for a in accounts]
    nama = {a["id"]: a.get("account_name") or a["id"] for a in accounts}
    hari = U.jumlah_hari(dari, sampai)
    pen = await U.analitik_penjualan(db, accounts, dari, sampai, kelompok="toko", bandingkan="periode_sebelumnya",
                                     limit=50)
    total = pen["total"]
    lalu = (pen.get("pembanding") or {}).get("total") or {}
    yoy = None
    if jenis == "bulanan":
        y = await U.analitik_penjualan(db, accounts, dari, sampai, kelompok="toko", bandingkan="tahun_lalu", limit=1)
        yoy = (y.get("pembanding") or {})
    plat = await U.analitik_penjualan(db, accounts, dari, sampai, kelompok="platform")
    kanal = await U.analitik_penjualan(db, accounts, dari, sampai, kelompok="kanal")
    harian = await U.analitik_penjualan(db, accounts, dari, sampai, kelompok="hari", limit=93)
    atas = await U.analitik_produk(db, accounts, dari, sampai, urut="teratas", cara="produk", limit=10)
    bawah = await U.analitik_produk(db, accounts, dari, sampai, urut="terbawah", cara="produk", limit=5)
    ik_toko = await U.analitik_iklan(db, accounts, dari, sampai, kelompok="toko", limit=50)
    ik_kamp = await U.analitik_iklan(db, accounts, dari, sampai, kelompok="kampanye", limit=20)
    live = await U.analitik_live(db, accounts, dari, sampai, kelompok="host", limit=10)
    setoran = await U.analitik_setoran(db, accounts, dari, sampai, kelompok="toko", limit=50)
    bulan = sorted({dari[:7], sampai[:7]})
    target = None
    try:
        target = await U.analitik_target(db, accounts, bulan)
    except Exception:  # noqa: BLE001 — target opsional
        target = None
    komplain = await _komplain(db, ids, dari, sampai)
    # Q-2 (keputusan owner 9 Nov) — omzet live RESMI = pesanan berkanal LIVE. Pembaca baku
    # `ukuran_penjualan.ringkas_live` (cabang MKT-INTI); bila belum ada, kanal LIVE dari rekap.
    live_resmi = None
    if hasattr(U, "ringkas_live"):
        try:
            live_resmi = await U.ringkas_live(db, accounts, dari, sampai)
        except Exception:  # noqa: BLE001 — bagian live opsional
            live_resmi = None
    rekap = await U.ringkas_omzet(db, accounts, dari, sampai)

    omzet = float(total.get("omzet") or 0)
    pesanan = int(total.get("pesanan") or 0)
    batal = int(total.get("batal_pesanan") or 0)
    belanja = float((ik_toko.get("total") or {}).get("belanja") or 0)
    omzet_iklan = float((ik_toko.get("total") or {}).get("omzet_atribusi") or 0)
    st_tot = setoran.get("total") or {}
    kpi = {
        "omzet": _rp(omzet), "pesanan": pesanan, "unit": int(total.get("unit") or 0),
        "pembeli": int(total.get("pembeli") or 0), "aov": _rp(total.get("aov")),
        "retur_nilai": _rp(total.get("retur_nilai")), "retur_pesanan": int(total.get("retur_pesanan") or 0),
        "omzet_setelah_retur": _rp(total.get("omzet_setelah_retur")),
        "batal_pesanan": batal, "persen_batal": _p(batal, pesanan + batal),
        "persen_retur": _p(total.get("retur_nilai"), omzet),
        "belanja_iklan": _rp(belanja), "omzet_atribusi_iklan": _rp(omzet_iklan),
        "roas_iklan": round(omzet_iklan / belanja, 2) if belanja else None,
        "tacos_persen": _p(belanja, omzet),
        "biaya_platform": _rp(st_tot.get("total_biaya")), "bruto_setoran": _rp(st_tot.get("bruto")),
        "biaya_platform_persen": st_tot.get("biaya_persen_dari_bruto"),
        "neto_diterima": _rp(st_tot.get("neto_diterima")),
        "hari": hari,
    }
    pembanding = {
        "periode_sebelumnya": {
            "periode": (pen.get("pembanding") or {}).get("periode"),
            "omzet": _rp(lalu.get("omzet")), "pesanan": int(lalu.get("pesanan") or 0), "aov": _rp(lalu.get("aov")),
            "selisih_omzet": _rp(omzet - float(lalu.get("omzet") or 0)),
            "selisih_omzet_persen": _p(omzet - float(lalu.get("omzet") or 0), float(lalu.get("omzet") or 0)),
            "selisih_pesanan": pesanan - int(lalu.get("pesanan") or 0),
        } if lalu else None,
        "tahun_lalu": ({"periode": yoy.get("periode"), "omzet": _rp((yoy.get("total") or {}).get("omzet")),
                        "selisih_omzet_persen": _p(omzet - float((yoy.get("total") or {}).get("omzet") or 0),
                                                   float((yoy.get("total") or {}).get("omzet") or 0))}
                       if yoy else None),
    }
    per_toko = []
    for r in (pen.get("kelompok") or {}).get("baris") or []:
        aid = r.get("kunci")
        t = (rekap.get("per_toko") or {}).get(aid) or {}
        per_toko.append({"toko": r.get("label") or nama.get(aid), "omzet": _rp(r.get("omzet")),
                         "pesanan": r.get("pesanan"), "porsi_persen": r.get("porsi_persen"),
                         "omzet_sebelumnya": _rp((r.get("pembanding") or {}).get("omzet")),
                         "selisih_persen": r.get("selisih_omzet_persen"),
                         "hari_ada_data": t.get("hari_ada_data"), "batal_pesanan": t.get("batal_pesanan"),
                         "retur_nilai": _rp(t.get("retur_nilai"))})
    iklan_per_toko = {r.get("label"): r for r in ik_toko.get("baris") or []}
    for t in per_toko:
        ik = iklan_per_toko.get(t["toko"]) or {}
        t["belanja_iklan"] = _rp(ik.get("belanja"))
        t["tacos_persen"] = _p(ik.get("belanja") or 0, t["omzet"])
    kampanye = [{"kampanye": r.get("label"), "belanja": _rp(r.get("belanja")),
                 "omzet_atribusi": _rp(r.get("omzet_atribusi")), "roas": r.get("roas"),
                 "biaya_per_konversi": _rp(r.get("biaya_per_konversi")) if r.get("biaya_per_konversi") else None}
                for r in ik_kamp.get("baris") or []]

    # ── anomali ───────────────────────────────────────────────────────────────
    anomali: List[dict] = []
    seri = [(r.get("label") or r.get("kunci"), float(r.get("omzet") or 0))
            for r in (harian.get("kelompok") or {}).get("baris") or []]
    if len(seri) >= 7:
        nilai = [v for _, v in seri]
        rata, sd = statistics.mean(nilai), statistics.pstdev(nilai)
        if sd > 0:
            for tgl, v in seri:
                z = (v - rata) / sd
                if abs(z) >= SIGMA:
                    anomali.append({"jenis": "omzet_harian", "tanggal": tgl, "omzet": _rp(v), "rata": _rp(rata),
                                    "z": round(z, 2), "arah": "naik" if z > 0 else "turun"})
    for t in per_toko:
        if t.get("hari_ada_data") is not None and hari >= 3 and t["hari_ada_data"] <= hari - 2:
            anomali.append({"jenis": "toko_tanpa_data", "toko": t["toko"], "hari_ada_data": t["hari_ada_data"],
                            "hari": hari})
    if lalu and int(lalu.get("pesanan") or 0) + int(lalu.get("batal_pesanan") or 0) >= 20:
        p_lalu = _p(lalu.get("batal_pesanan") or 0, int(lalu.get("pesanan") or 0) + int(lalu.get("batal_pesanan") or 0))
        p_kini = kpi["persen_batal"]
        if p_kini is not None and p_lalu is not None and p_kini >= 2 * max(p_lalu, 0.1) and p_kini - p_lalu >= 5:
            anomali.append({"jenis": "batal_melonjak", "persen_batal": p_kini, "persen_batal_sebelumnya": p_lalu})
    for k in kampanye:
        if k["belanja"] and (k["roas"] is None or k["roas"] < 1) and belanja and k["belanja"] >= 0.05 * belanja:
            anomali.append({"jenis": "kampanye_rugi", "kampanye": k["kampanye"], "belanja": k["belanja"],
                            "roas": k["roas"]})
    if kpi["bruto_setoran"] and omzet:
        sel = _p(kpi["bruto_setoran"] - omzet, omzet)
        if sel is not None and abs(sel) >= 10:
            anomali.append({"jenis": "selisih_setoran", "bruto_setoran": kpi["bruto_setoran"], "omzet": kpi["omzet"],
                            "selisih_persen": sel})

    kualitas = {
        "toko": len(accounts), "hari": hari,
        "toko_tanpa_iklan": [t["toko"] for t in per_toko if t["omzet"] and not t["belanja_iklan"]],
        "toko_tanpa_setoran": [t["toko"] for t in per_toko
                               if t["omzet"] and not any(r.get("label") == t["toko"] for r in setoran.get("baris") or [])],
        "catatan": list(dict.fromkeys((pen.get("catatan") or []) + (ik_toko.get("catatan") or [])
                                      + (setoran.get("catatan") or [])))[:8],
    }
    fakta = {
        "versi": VERSI, "jenis": jenis, "label": label, "cv": cv,
        "periode": {"dari": dari, "sampai": sampai, "hari": hari},
        "definisi": {
            "omzet": U.DEFINISI_OMZET,
            "tacos": "TACoS = belanja iklan ÷ omzet toko × 100.",
            "roas": "ROAS iklan = omzet atribusi platform ÷ belanja iklan (atribusi platform, BUKAN omzet tambahan).",
            "biaya_platform": "Biaya platform dari laporan dana dilepas (tanggal dana dilepas, bisa tertinggal).",
        },
        "kpi": kpi, "pembanding": pembanding,
        "per_toko": per_toko,
        "per_platform": _ringkas_baris((plat.get("kelompok") or {}).get("baris") or [],
                                       ("label", "omzet", "pesanan", "porsi_persen"), 10),
        "per_kanal": _ringkas_baris((kanal.get("kelompok") or {}).get("baris") or [],
                                    ("label", "omzet", "pesanan", "porsi_persen"), 12),
        "harian": [{"tanggal": t, "omzet": _rp(v)} for t, v in seri][:93],
        "produk_teratas": _ringkas_baris(atas.get("baris") or [], ("label", "omzet", "unit", "pesanan",
                                                                   "laba_kotor", "margin_persen"), 10),
        "produk_total": atas.get("total"),
        "produk_terbawah": _ringkas_baris(bawah.get("baris") or [], ("label", "omzet", "unit", "pesanan"), 5),
        "iklan_kampanye": kampanye,
        "live": {"resmi": (({k: live_resmi.get(k) for k in ("omzet", "pesanan", "sesi", "omzet_tercatat_sesi",
                                                              "selisih_tercatat", "definisi")})
                           if live_resmi else _live_dari_kanal(kanal)),
                 "total": live.get("total"), "host": _ringkas_baris(live.get("baris") or [],
                                                                     ("label", "omzet", "sesi", "jam_live",
                                                                      "omzet_per_jam"), 10)},
        "setoran": {"total": st_tot, "per_toko": _ringkas_baris(setoran.get("baris") or [],
                                                                ("label", "bruto", "total_biaya",
                                                                 "biaya_persen_dari_bruto", "neto_diterima"), 20)},
        "target": _ringkas_target(target, U),
        "komplain": komplain,
        "anomali": anomali,
        "kualitas_data": kualitas,
    }
    return fakta


def _live_dari_kanal(kanal: dict) -> Optional[dict]:
    for r in (kanal.get("kelompok") or {}).get("baris") or []:
        if str(r.get("kunci") or r.get("label") or "").lower() == "live":
            return {"omzet": _rp(r.get("omzet")), "pesanan": r.get("pesanan"),
                    "definisi": "Omzet live = pesanan berkanal LIVE (rincian kanal pesanan)."}
    return None


def _ringkas_target(t: Optional[dict], U_mod=None) -> Optional[dict]:
    if not t:
        return None
    out = {k: t.get(k) for k in ("bulan", "catatan") if k in t}
    # persen total versi lama (omzet SEMUA toko ÷ target toko bertarget) sengaja dibuang
    out["total"] = {k: v for k, v in (t.get("total") or {}).items() if k != "capaian_omzet_persen"}
    # M-04 — persen capaian GABUNGAN hanya dari toko yang punya target (pembaca baku MKT-INTI
    # `capaian_gabungan`; cadangan: rumus yang sama di sini).
    baris = t.get("baris") or []
    if U_mod is not None and hasattr(U_mod, "capaian_gabungan"):
        gab = U_mod.capaian_gabungan(baris, lambda b: b.get("target_omzet"), lambda b: b.get("aktual_omzet"))
    else:
        tgt = sum(float(b.get("target_omzet") or 0) for b in baris if b.get("target_omzet"))
        akt = sum(float(b.get("aktual_omzet") or 0) for b in baris if b.get("target_omzet"))
        tanpa = sum(float(b.get("aktual_omzet") or 0) for b in baris if not b.get("target_omzet"))
        gab = {"target": tgt, "aktual_bertarget": akt, "aktual_tanpa_target": tanpa,
               "toko_bertarget": sum(1 for b in baris if b.get("target_omzet")),
               "toko_tanpa_target": sum(1 for b in baris if not b.get("target_omzet")),
               "persen": round(akt / tgt * 100, 1) if tgt > 0 else None}
    out["capaian_gabungan"] = {k: (_rp(v) if k in ("target", "aktual_bertarget", "aktual_tanpa_target") else v)
                               for k, v in gab.items()}
    if t.get("baris"):
        out["per_toko"] = _ringkas_baris(t["baris"], ("toko", "label_bulan", "target_omzet", "aktual_omzet",
                                                      "capaian_omzet_persen", "proyeksi_omzet_akhir_bulan",
                                                      "proyeksi_capaian_persen", "status"), 20)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ANGKA SAH & PENJAGA ANTI-HALUSINASI
# ═══════════════════════════════════════════════════════════════════════════════
def angka_dari(obj: Any) -> List[float]:
    """Semua angka di dalam paket fakta (nilai numerik, bukan teks)."""
    out: List[float] = []

    def jalan(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            if math.isfinite(float(v)):
                out.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                jalan(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                jalan(x)
    jalan(obj)
    return sorted(set(out))


_RX_ANGKA = re.compile(
    r"(?<![\w/])(?P<rp>Rp\s?)?(?P<neg>[−-])?(?P<num>\d[\d.,]*\d|\d)\s?(?P<unit>%|persen|jt|juta|rb|ribu|miliar|M\b|K\b)?",
    re.IGNORECASE)
_RX_TANGGAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_PENGALI = {"jt": 1e6, "juta": 1e6, "rb": 1e3, "ribu": 1e3, "miliar": 1e9, "m": 1e9, "k": 1e3}


def _urai_angka_teks(m: re.Match) -> Tuple[Optional[float], float]:
    """(nilai, toleransi tampilan) dari satu angka di teks gaya Indonesia."""
    s = m.group("num")
    unit = (m.group("unit") or "").lower()
    dec = 0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            ip, fp = s.replace(".", "").split(",", 1)
        else:
            ip, fp = s.replace(",", "").split(".", 1)
        dec = len(fp)
        v = float(f"{ip}.{fp}")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            dec = len(parts[1])
            v = float(f"{parts[0]}.{parts[1]}")
        else:
            v = float(s.replace(",", ""))
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) != 3:
            dec = len(parts[1])
            v = float(s)
        else:
            v = float(s.replace(".", ""))
    else:
        v = float(s)
    mult = _PENGALI.get(unit, 1.0)
    tol = 0.5 * (10 ** -dec) * mult if mult != 1.0 or dec else 1.0
    if unit in ("%", "persen"):
        tol = max(tol, 0.05)
    if m.group("neg"):
        v = -v
    return v * mult, max(tol, 1.0 if mult == 1.0 and unit not in ("%", "persen") else tol)


def teks_laporan(spec: dict) -> Iterable[str]:
    yield str(spec.get("judul") or "")
    yield str(spec.get("subjudul") or "")
    for b in spec.get("bagian") or []:
        yield str(b.get("judul") or "")
        yield str(b.get("teks") or "")
        t = b.get("tabel") or {}
        for row in t.get("baris") or []:
            for c in row:
                if isinstance(c, str):
                    yield c
        g = b.get("grafik") or {}
        yield str(g.get("judul") or "")


def angka_laporan(spec: dict) -> List[Tuple[float, float, str]]:
    """Semua angka dalam laporan AI → [(nilai, toleransi, teks asli)]."""
    out: List[Tuple[float, float, str]] = []
    for teks in teks_laporan(spec):
        bersih = _RX_TANGGAL.sub(" ", teks)
        for m in _RX_ANGKA.finditer(bersih):
            try:
                v, tol = _urai_angka_teks(m)
            except ValueError:
                continue
            out.append((v, tol, m.group(0).strip()))
    for b in spec.get("bagian") or []:
        for row in (b.get("tabel") or {}).get("baris") or []:
            for c in row:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    out.append((float(c), 1.0 if abs(float(c)) >= 100 else 0.05, str(c)))
        for s in (b.get("grafik") or {}).get("seri") or []:
            for c in s.get("nilai") or []:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    out.append((float(c), 1.0 if abs(float(c)) >= 100 else 0.05, str(c)))
    return out


def _sah_bebas(v: float, raw: str) -> bool:
    """Angka yang tidak perlu ada di fakta: urutan/hitungan kecil, tahun, peringkat."""
    if "%" in raw or "persen" in raw.lower() or raw.lower().startswith("rp"):
        return False
    if float(v).is_integer() and 0 <= v <= 31:
        return True
    if float(v).is_integer() and 2000 <= v <= 2100:
        return True
    return False


def periksa_angka(spec: dict, fakta: dict, *, tambahan: Iterable[float] = ()) -> List[str]:
    """Angka di laporan yang TIDAK ada di paket fakta (kosong = lolos)."""
    sah = angka_dari(fakta) + [float(x) for x in tambahan]
    sah_abs = sorted({abs(x) for x in sah})
    asing: List[str] = []
    import bisect
    for v, tol, raw in angka_laporan(spec):
        if _sah_bebas(v, raw):
            continue
        a = abs(v)
        tol_rel = max(tol, a * 0.005)        # pembulatan tampilan ±0,5 %
        i = bisect.bisect_left(sah_abs, a - tol_rel)
        if i < len(sah_abs) and sah_abs[i] <= a + tol_rel:
            continue
        asing.append(raw)
    return list(dict.fromkeys(asing))[:12]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SIMPAN PAKET FAKTA & BUKA PERCAKAPAN ASISTEN AI
# ═══════════════════════════════════════════════════════════════════════════════
async def simpan_fakta(db, fakta: dict, user: dict) -> str:
    fid = f"fakta-{uuid.uuid4().hex[:12]}"
    await db[KOLEKSI_FAKTA].insert_one({"id": fid, "user_id": user.get("id"), "fakta": fakta,
                                        "dibuat": datetime.now(timezone.utc)})
    return fid


async def ambil_fakta(db, fakta_id: str, user: dict) -> Optional[dict]:
    d = await db[KOLEKSI_FAKTA].find_one({"id": fakta_id, "user_id": user.get("id")}, {"_id": 0})
    return (d or {}).get("fakta")


def prompt_laporan(jenis: str, dari: str, sampai: str, label: str, toko_id: Optional[str] = None) -> str:
    toko = f', toko_id "{toko_id}"' if toko_id else ""
    return (
        f"Buat Laporan Marketing {jenis} periode {label} ({dari} s/d {sampai}). Langkah: (1) panggil "
        f"paket_laporan_marketing dengan jenis \"{jenis}\", dari \"{dari}\", sampai \"{sampai}\"{toko}; (2) baca "
        "angkanya dan tulis analisis yang benar-benar berguna: ringkasan eksekutif 3–5 kalimat (apa yang berubah, "
        "kenapa, tindakan), KPI vs periode sebelumnya, per toko/platform/kanal, produk teratas & terbawah, iklan "
        "(kampanye rugi & efisien, TACoS), live/KOL, retur/batal/komplain, biaya platform, anomali, kualitas data, dan "
        "paling banyak 5 rekomendasi berangka dengan perkiraan dampak; (3) panggil buat_laporan_marketing dengan "
        "fakta_id dari langkah 1 dan format PDF serta Excel. Pakai HANYA angka dari paket fakta — penjaga angka menolak "
        "laporan yang memuat angka lain. Jangan mengubah atau menyiapkan perubahan data apa pun."
    )


def _bearer(request) -> Optional[str]:
    h = request.headers.get("Authorization") or ""
    return h.split(" ", 1)[1].strip() if h.startswith("Bearer ") and " " in h else None


async def mulai_percakapan(request, user: dict, *, judul: str, teks: str, cv: Optional[str] = None) -> dict:
    """Percakapan Asisten AI baru yang langsung menjawab ``teks`` di latar (seperti chat biasa)."""
    from fastapi import HTTPException
    from core.asisten_ai import mesin, simpan
    from database import get_db
    from utils.waktu import today_wib
    db = get_db()
    cv = (cv or request.headers.get("X-CV") or "DA").upper()
    if cv not in ("DA", "SMU", "ALL"):
        cv = "DA"
    sesi = await simpan.buat_sesi(db, user["id"], judul)
    sesi_doc = await simpan.ambil_sesi(db, user["id"], sesi["id"])
    today = today_wib()
    jalan, galat = await mesin.siapkan_jalan(db=db, user=user, sesi=sesi_doc, teks=teks[:mesin.MAKS_TEKS_PENGGUNA],
                                             cv=cv, periode=today.strftime("%Y-%m"), today=today,
                                             token=_bearer(request), app=request.app)
    if galat:
        raise HTTPException(503, galat["pesan"])
    mesin.mulai(jalan)
    return {"ok": True, "sesi_id": sesi["id"],
            "pesan": "Asisten AI sedang menyusun jawabannya. Percakapan dibuka di menu Asisten AI."}
