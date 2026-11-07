"""Alat baca SKENARIO TARGET toko (Asisten AI Tahap B, agen pemasaran — 8 Nov 2026).

Tiga usulan target (konservatif / realistis / agresif) per toko untuk satu bulan, dihitung dari omzet
3–6 bulan terakhir yang LENGKAP + pola musim tahun lalu bila datanya ada. Semua angka dibaca lewat
``GET /api/marketing/analitik/target`` dengan token pemakai (``ctx.api``), jadi definisi omzet baku
(`core.ukuran_penjualan`), pilihan CV, dan lingkup toko berlaku persis seperti layar.

Alat ini HANYA MEMBACA. Untuk memasang, model memanggil alat tindakan ``pasang_target_toko`` (kartu
konfirmasi); hasil di sini menyediakan ``isian_pasang_target`` yang siap dipakai sebagai isiannya.

Rumus (dinyatakan juga di ``asumsi`` pada hasil, supaya pemakai bisa menilai):
  dasar D   = rata-rata omzet bulanan pada bulan dasar yang berdata (> 0);
  tren T    = kemiringan garis lurus omzet bulan dasar ÷ D, per bulan, dibatasi ±10%; dampaknya
              T × jarak (bulan dari titik tengah bulan dasar ke bulan target), dibatasi ±25%;
  musim S   = omzet bulan yang sama tahun lalu ÷ rata-rata bulan dasar tahun lalu (≥ 2 bulan
              berdata), dibatasi 0,7–1,6; tanpa data tahun lalu S = 1;
  proyeksi  = D × (1 + dampak tren) × S;
  skenario  = proyeksi × (1 + persen skenario) — bawaan konservatif −10%, realistis 0%, agresif +20%;
  pesanan   = rata-rata pesanan × faktor yang sama (nilai rata-rata per pesanan dianggap tetap).
Pembulatan: omzet ke Rp 100.000 (≥ Rp 10 jt; di bawahnya Rp 10.000/Rp 1.000), pesanan ke puluhan.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import AlatError, alat
from core import ukuran_penjualan as U

BULAN = {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"}
SKENARIO = ("konservatif", "realistis", "agresif")
BAWAAN_PERSEN = {"konservatif": -10.0, "realistis": 0.0, "agresif": 20.0}
BATAS_TREN_BULAN = 0.10
BATAS_TREN_TOTAL = 0.25
BATAS_MUSIM = (0.7, 1.6)
MAKS_BULAN_DEPAN = 12
MAKS_KARAKTER = 14_000

DESKRIPSI = (
    "Menyusun TIGA skenario target omzet (Rp) dan pesanan per toko online untuk satu bulan: konservatif, "
    "realistis, agresif. Dasarnya omzet 3–6 bulan terakhir yang sudah lengkap (definisi omzet baku: "
    "penjualan produk setelah diskon penjual, sebelum potongan platform; batal & belum dibayar tidak "
    "dihitung), tren bulanan, dan pola musim dari bulan yang sama tahun lalu bila datanya ada (mis. "
    "lonjakan akhir tahun). Mengikuti CV yang dipilih dan hanya toko yang boleh dilihat pengguna.\n"
    "Hasil per toko: omzet & pesanan bulan dasar, rata_rata_omzet, tren_per_bulan_persen, faktor_musim "
    "(dan dari mana), proyeksi_omzet, target_sekarang (bila sudah ada), progres bulan berjalan, dan "
    "skenario {konservatif|realistis|agresif: target_omzet, target_pesanan, vs_rata_rata_persen, "
    "vs_tahun_lalu_persen}; ditambah tabel_skenario (satu baris per toko: konservatif, realistis, agresif; "
    "target_omzet & target_pesanan = realistis), total semua toko, daftar ASUMSI yang wajib disampaikan ke "
    "pengguna, dan isian_pasang_target (isian siap pakai untuk alat pasang_target_toko per skenario).\n"
    "Bawaan: bulan = bulan depan, bulan_dasar = 3, persen skenario −10% / 0% / +20% dari proyeksi "
    "(bisa diubah). Hanya MEMBACA; tidak memasang target. Sampaikan skenario dulu, lalu pakai "
    "pasang_target_toko hanya bila pengguna memintanya.")


# ── pembantu murni (diuji langsung) ─────────────────────────────────────────
def geser_bulan(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def jarak_bulan(a: str, b: str) -> int:
    """Banyak bulan dari ``a`` ke ``b`` (b − a)."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def _setengah_ke_atas(x: float) -> int:
    return int(math.floor(x + 0.5 + 1e-9))       # bukan round() bawaan (pembulatan bankir)


def bulat_rp(v: float) -> float:
    v = max(0.0, float(v or 0))
    langkah = 100_000 if v >= 10_000_000 else 10_000 if v >= 1_000_000 else 1_000
    return float(_setengah_ke_atas(v / langkah) * langkah)


def bulat_pesanan(v: float) -> int:
    v = max(0.0, float(v or 0))
    return _setengah_ke_atas(v / 10) * 10 if v >= 100 else _setengah_ke_atas(v)


def _batas(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pct(a: float, b: float) -> Optional[float]:
    return round((a / b - 1) * 100, 1) if b else None


def tren_bulanan(nilai: Sequence[float]) -> float:
    """Kemiringan garis lurus (kuadrat terkecil) atas bulan berdata ÷ rata-ratanya, dibatasi ±10%/bulan.

    Bulan nol di awal (toko baru) tidak ikut; kurang dari 2 bulan berdata = tanpa tren."""
    titik = [(i, float(v)) for i, v in enumerate(nilai) if float(v or 0) > 0]
    if len(titik) < 2:
        return 0.0
    n = len(titik)
    mx = sum(i for i, _ in titik) / n
    my = sum(v for _, v in titik) / n
    sxx = sum((i - mx) ** 2 for i, _ in titik)
    if not sxx or not my:
        return 0.0
    slope = sum((i - mx) * (v - my) for i, v in titik) / sxx
    return _batas(slope / my, -BATAS_TREN_BULAN, BATAS_TREN_BULAN)


def faktor_musim(ly_dasar: Sequence[float], ly_target: Optional[float]) -> Optional[float]:
    aktif = [float(v) for v in ly_dasar if float(v or 0) > 0]
    if not ly_target or ly_target <= 0 or len(aktif) < 2:
        return None
    return round(_batas(float(ly_target) / (sum(aktif) / len(aktif)), *BATAS_MUSIM), 3)


def hitung_toko(omzet: Sequence[float], pesanan: Sequence[int], *, jarak: float,
                ly_dasar: Sequence[float] = (), ly_target: Optional[float] = None,
                persen: Optional[Dict[str, float]] = None) -> Optional[dict]:
    """Skenario satu toko. ``None`` bila bulan dasar tidak berdata sama sekali."""
    persen = {**BAWAAN_PERSEN, **(persen or {})}
    idx = [i for i, v in enumerate(omzet) if float(v or 0) > 0]
    if not idx:
        return None
    d = sum(float(omzet[i]) for i in idx) / len(idx)
    dp = sum(float(pesanan[i] or 0) for i in idx) / len(idx)
    t = tren_bulanan(omzet)
    efek = _batas(t * jarak, -BATAS_TREN_TOTAL, BATAS_TREN_TOTAL)
    s = faktor_musim(ly_dasar, ly_target)
    faktor = (1 + efek) * (s or 1.0)
    proyeksi = d * faktor
    sk = {}
    for nama in SKENARIO:
        k = 1 + persen[nama] / 100
        o = bulat_rp(proyeksi * k)
        row = {"target_omzet": o, "target_pesanan": bulat_pesanan(dp * faktor * k),
               "vs_rata_rata_persen": _pct(o, d)}
        if ly_target:
            row["vs_tahun_lalu_persen"] = _pct(o, float(ly_target))
        sk[nama] = row
    return {"rata_rata_omzet": bulat_rp(d), "rata_rata_pesanan": int(round(dp)),
            "bulan_berdata": len(idx), "tren_per_bulan_persen": round(t * 100, 1),
            "dampak_tren_persen": round(efek * 100, 1), "faktor_musim": s,
            "proyeksi_omzet": bulat_rp(proyeksi), "skenario": sk}


# ── alat ────────────────────────────────────────────────────────────────────
def _persen(args: dict) -> Dict[str, float]:
    p = {nama: float(args.get(f"persen_{nama}", BAWAAN_PERSEN[nama])) for nama in SKENARIO}
    if not (p["konservatif"] < p["realistis"] < p["agresif"]):
        raise AlatError(400, "Persen skenario harus berurutan: konservatif < realistis < agresif.")
    return p


def _per_toko(data: dict) -> Dict[str, Dict[str, dict]]:
    out: Dict[str, Dict[str, dict]] = {}
    for r in (data or {}).get("baris") or []:
        if r.get("toko_id") and r.get("bulan"):
            out.setdefault(r["toko_id"], {})[r["bulan"]] = r
    return out


def _nama_toko(data: dict) -> Dict[str, str]:
    return {r["toko_id"]: r.get("toko") or r["toko_id"] for r in (data or {}).get("baris") or []
            if r.get("toko_id")}


def _ringkas_bulan(bulan: Sequence[str]) -> str:
    if not bulan:
        return "—"
    a, b = U.label_bulan(bulan[0]), U.label_bulan(bulan[-1])
    return a if a == b else f"{a} – {b}"


def _padatkan(hasil: dict) -> dict:
    def _len():
        return len(json.dumps(hasil, ensure_ascii=False, default=str))
    if _len() > MAKS_KARAKTER:
        for t in hasil["toko"]:
            t.pop("bulan_dasar", None)
        hasil.setdefault("catatan", []).append("Rincian omzet per bulan dasar tidak ditampilkan supaya ringkas.")
    if _len() > MAKS_KARAKTER:
        hasil["isian_pasang_target"] = {"realistis": hasil["isian_pasang_target"].get("realistis")}
    while _len() > MAKS_KARAKTER and len(hasil["toko"]) > 1:
        buang = max(1, len(hasil["toko"]) // 5)
        del hasil["toko"][-buang:]
        hasil["dipotong_untuk_ai"] = ("Sebagian toko dengan omzet terkecil tidak ditampilkan; tanyakan per toko "
                                      "(toko_id) untuk melihatnya.")
        sisa = {t["toko_id"] for t in hasil["toko"]}
        hasil["tabel_skenario"] = [x for x in hasil["tabel_skenario"] if x["toko_id"] in sisa]
        for k, v in list(hasil["isian_pasang_target"].items()):
            if v:
                v["toko"] = [x for x in v["toko"] if x["toko_id"] in sisa]
    return hasil


@alat(
    name="skenario_target",
    kind="read",
    label="Menyusun skenario target toko",
    description=DESKRIPSI,
    input_schema={
        "type": "object",
        "properties": {
            "bulan": {**BULAN, "description": "Bulan target (TTTT-BB). Bawaan: bulan depan. Paling awal bulan "
                                              "berjalan, paling jauh 12 bulan ke depan."},
            "bulan_dasar": {"type": "integer", "minimum": 3, "maximum": 6,
                            "description": "Banyak bulan lengkap terakhir yang dijadikan dasar (3–6). Bawaan 3."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional; tanpa ini semua toko)."},
            "persen_konservatif": {"type": "number", "minimum": -50, "maximum": 50,
                                   "description": "Persen dari proyeksi untuk skenario konservatif. Bawaan -10."},
            "persen_realistis": {"type": "number", "minimum": -30, "maximum": 60,
                                 "description": "Persen dari proyeksi untuk skenario realistis. Bawaan 0."},
            "persen_agresif": {"type": "number", "minimum": 0, "maximum": 100,
                               "description": "Persen dari proyeksi untuk skenario agresif. Bawaan 20."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="penjualan",
)
async def skenario_target(ctx, args: dict) -> dict:
    args = args or {}
    persen = _persen(args)
    sekarang = B.bulan_ini(ctx)
    target = args.get("bulan") or geser_bulan(sekarang, 1)
    if jarak_bulan(sekarang, target) < 0:
        raise AlatError(400, f"Skenario hanya untuk bulan berjalan atau sesudahnya; {U.label_bulan(target)} "
                             "sudah lewat. Untuk bulan lalu pakai alat target_toko (target vs aktual).")
    if jarak_bulan(sekarang, target) > MAKS_BULAN_DEPAN:
        raise AlatError(400, f"Bulan target paling jauh {MAKS_BULAN_DEPAN} bulan dari sekarang.")
    k = B.angka(args.get("bulan_dasar"), 3, 6, 3)
    akhir_dasar = geser_bulan(sekarang, -1)          # bulan lengkap terakhir
    bulan_dasar = [geser_bulan(akhir_dasar, -i) for i in range(k - 1, -1, -1)]
    jarak = jarak_bulan(akhir_dasar, target) + (k - 1) / 2
    toko_id = args.get("toko_id")

    kini = await ctx.api("GET", "/api/marketing/analitik/target", params=B.params(
        dari_bulan=bulan_dasar[0], sampai_bulan=target, toko_id=toko_id))
    lalu = await ctx.api("GET", "/api/marketing/analitik/target", params=B.params(
        dari_bulan=geser_bulan(bulan_dasar[0], -12), sampai_bulan=geser_bulan(target, -12), toko_id=toko_id))
    per, per_lalu, nama = _per_toko(kini), _per_toko(lalu), _nama_toko(kini)
    ly_target_bulan = geser_bulan(target, -12)
    ly_dasar_bulan = [geser_bulan(b, -12) for b in bulan_dasar]

    toko_out: List[dict] = []
    tanpa_data: List[str] = []
    ada_musim = False
    for tid, bln in per.items():
        omzet = [float((bln.get(b) or {}).get("aktual_omzet") or 0) for b in bulan_dasar]
        pesanan = [int((bln.get(b) or {}).get("aktual_pesanan") or 0) for b in bulan_dasar]
        lb = per_lalu.get(tid) or {}
        ly_t = float((lb.get(ly_target_bulan) or {}).get("aktual_omzet") or 0) or None
        ly_d = [float((lb.get(b) or {}).get("aktual_omzet") or 0) for b in ly_dasar_bulan]
        h = hitung_toko(omzet, pesanan, jarak=jarak, ly_dasar=ly_d, ly_target=ly_t, persen=persen)
        if h is None:
            tanpa_data.append(nama.get(tid, tid))
            continue
        catatan: List[str] = []
        if h["bulan_berdata"] < k:
            catatan.append(f"Hanya {h['bulan_berdata']} dari {k} bulan dasar yang berdata.")
        if h["faktor_musim"] is not None:
            ada_musim = True
            h["dasar_musim"] = (f"{U.label_bulan(ly_target_bulan)} ÷ rata-rata "
                                f"{_ringkas_bulan(ly_dasar_bulan)}")
            h["omzet_tahun_lalu"] = bulat_rp(ly_t or 0)
        tgt = bln.get(target) or {}
        row = {"toko_id": tid, "toko": nama.get(tid, tid),
               "bulan_dasar": [{"bulan": U.label_bulan(b), "omzet": bulat_rp(o), "pesanan": p}
                               for b, o, p in zip(bulan_dasar, omzet, pesanan)],
               **h,
               "target_sekarang": ({"omzet": tgt.get("target_omzet"), "pesanan": tgt.get("target_pesanan")}
                                   if tgt.get("target_omzet") else None)}
        jalan = bln.get(sekarang) or {}
        if jalan.get("bulan_berjalan"):
            row["bulan_berjalan"] = {"bulan": U.label_bulan(sekarang), "aktual_omzet": bulat_rp(jalan.get("aktual_omzet") or 0),
                                     "hari_berlalu": jalan.get("hari_berlalu"),
                                     "proyeksi_akhir_bulan": bulat_rp(jalan.get("proyeksi_omzet_akhir_bulan") or 0)}
        if catatan:
            row["catatan"] = catatan
        toko_out.append(row)
    toko_out.sort(key=lambda r: -r["proyeksi_omzet"])

    total = {"rata_rata_omzet": bulat_rp(sum(t["rata_rata_omzet"] for t in toko_out)),
             "proyeksi_omzet": bulat_rp(sum(t["proyeksi_omzet"] for t in toko_out)),
             "target_sekarang": bulat_rp(sum((t["target_sekarang"] or {}).get("omzet") or 0 for t in toko_out))
             or None}
    for nm in SKENARIO:
        total[nm] = bulat_rp(sum(t["skenario"][nm]["target_omzet"] for t in toko_out))
    asumsi = [
        f"Dasar = rata-rata omzet {_ringkas_bulan(bulan_dasar)} ({k} bulan lengkap terakhir; bulan berjalan "
        "tidak dipakai karena belum lengkap).",
        "Omzet memakai definisi baku: penjualan produk setelah diskon penjual, sebelum potongan platform; "
        "batal dan belum dibayar tidak dihitung; retur tidak dikurangkan.",
        f"Tren = kemiringan garis lurus omzet bulan dasar per bulan (dibatasi ±{int(BATAS_TREN_BULAN * 100)}%), "
        f"diterapkan sejauh {jarak:g} bulan dari titik tengah bulan dasar ke bulan target "
        f"(dibatasi ±{int(BATAS_TREN_TOTAL * 100)}%).",
        (f"Musim = {U.label_bulan(ly_target_bulan)} dibanding rata-rata {_ringkas_bulan(ly_dasar_bulan)} per toko "
         f"(dibatasi {BATAS_MUSIM[0]:g}–{BATAS_MUSIM[1]:g}×); toko tanpa data tahun lalu memakai faktor 1."
         if ada_musim else
         f"Tidak ada data {U.label_bulan(ly_target_bulan)} dan bulan dasar tahun lalu, jadi pola musim (mis. "
         "kampanye tanggal kembar) BELUM diperhitungkan — sampaikan ini ke pengguna."),
        "Skenario dari proyeksi: konservatif {konservatif:+g}%, realistis {realistis:+g}%, agresif {agresif:+g}%; "
        "target pesanan memakai faktor yang sama (nilai rata-rata per pesanan dianggap tetap).".format(**persen),
        "Belum memperhitungkan stok barang jadi, kapasitas produksi, dan rencana anggaran iklan.",
    ]
    hasil = {
        "bulan_target": target, "label_bulan_target": U.label_bulan(target), "periode": target,
        "bulan_dasar": bulan_dasar, "cv": kini.get("cv_label") or kini.get("cv") or ctx.cv,
        # ringkas satu baris per toko (siap untuk tampilkan_tabel); target_omzet/target_pesanan = skenario realistis
        "tabel_skenario": [{"toko_id": t["toko_id"], "toko": t["toko"],
                            **{nm: t["skenario"][nm]["target_omzet"] for nm in SKENARIO},
                            "target_omzet": t["skenario"]["realistis"]["target_omzet"],
                            "target_pesanan": t["skenario"]["realistis"]["target_pesanan"]} for t in toko_out],
        "asumsi": asumsi, "toko": toko_out, "total": total,
        "toko_tanpa_data": tanpa_data,
        "isian_pasang_target": {nm: {"bulan": target, "skenario": nm,
                                     "toko": [{"toko_id": t["toko_id"],
                                               "target_omzet": t["skenario"][nm]["target_omzet"],
                                               "target_pesanan": t["skenario"][nm]["target_pesanan"]}
                                              for t in toko_out]}
                                for nm in SKENARIO},
        "catatan": list(kini.get("catatan") or []) + (
            [f"{len(tanpa_data)} toko tanpa penjualan di bulan dasar tidak diberi skenario."] if tanpa_data else []),
    }
    if not toko_out:
        hasil["catatan"].append("Tidak ada toko berdata pada bulan dasar; skenario tidak bisa disusun.")
    return {"hasil": _padatkan(hasil), "_sumber": "Rekap penjualan harian & target toko Marketing"}
