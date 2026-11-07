"""Alat baca Asisten AI — keuangan (Kontrak A). Semua angka dari endpoint Portal Keuangan lewat `ctx.api`
(hak akses pengguna + CV terpilih berlaku; tanpa Portal Keuangan → 403 yang ramah).

CV: parameter query `entity` = CV aktif (DA | SMU | ALL). Endpoint keuangan menerima ALL (Gabungan) dan
menyajikannya SETELAH eliminasi transaksi antar CV; laba rugi Gabungan juga diberi rincian per CV.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat
from core.asisten_ai.alat._bantu_laporan import (
    SKEMA_PERIODE, coba, cv_aktif, hari_ini, label_cv, label_tanggal, pangkas, param_cv, periode, perubahan, persen,
    rp, samaran, saring_akun_gaji, tanggal_sah,
)

P_LABA_RUGI = "/api/rahaza/finance/reports/profit-loss"
P_NERACA = "/api/rahaza/finance/reports/balance-sheet"
P_ARUS_KAS = "/api/rahaza/finance/reports/cash-flow"
P_REKENING = "/api/rahaza/cash-accounts"
P_PIUTANG = "/api/rahaza/ar-aging"
P_HUTANG = "/api/rahaza/ap-aging"

LABEL_UMUR = {"current": "Belum jatuh tempo", "1_30": "Telat 1–30 hari", "31_60": "Telat 31–60 hari",
              "61_90": "Telat 61–90 hari", "90_plus": "Telat > 90 hari", "tanpa_jatuh_tempo": "Tanpa jatuh tempo"}


# ── laba rugi ────────────────────────────────────────────────────────────────
def _ringkas_lr(d: dict) -> dict:
    t = (d or {}).get("totals") or {}
    out = {"pendapatan": rp(t.get("revenue")), "hpp": rp(t.get("cogs")), "laba_kotor": rp(t.get("gross_profit")),
           "beban_operasional": rp(t.get("expense")), "laba_operasi": rp(t.get("operating_income")),
           "pendapatan_lain": rp(t.get("other_income")), "beban_lain": rp(t.get("other_expense")),
           "laba_bersih": rp(t.get("net_income"))}
    out["margin_kotor_pct"] = persen(out["laba_kotor"], out["pendapatan"])
    out["margin_bersih_pct"] = persen(out["laba_bersih"], out["pendapatan"])
    return out


def _akun_terbesar(ctx, d: dict, grup: str, n: int, pembanding: dict | None = None) -> tuple:
    """(akun terbesar satu kelompok, catatan gaji|None). Akun gaji digabung (owner/SDM) atau tidak dirinci."""
    akun = (((d or {}).get("groups") or {}).get(grup) or {}).get("accounts") or []
    lalu = {a.get("code"): a.get("amount") for a in
            ((((pembanding or {}).get("groups") or {}).get(grup) or {}).get("accounts") or [])}
    akun = [{**a, "_lalu": float(lalu.get(a.get("code")) or 0)} for a in akun]
    akun, catatan = saring_akun_gaji(ctx, akun, "name", ("amount", "_lalu"), kode="code")
    rows = sorted((a for a in akun if rp(a.get("amount"))), key=lambda a: -abs(float(a.get("amount") or 0)))[:n]
    out = []
    for a in rows:
        r = {"kode": a.get("code"), "akun": a.get("name"), "nilai": rp(a.get("amount"))}
        if pembanding is not None:
            r["pembanding"] = rp(a.get("_lalu"))
        out.append(r)
    return out, catatan


@alat(
    name="laba_rugi",
    kind="read",
    label="Membaca laba rugi",
    description=(
        "Laba rugi buku besar CV aktif untuk satu bulan (bawaan: bulan berjalan s.d. hari ini) atau rentang "
        "tanggal, dibanding periode sebelumnya (bulan berjalan dibanding tanggal yang sama bulan lalu). "
        "Mengembalikan pendapatan, HPP, laba kotor, beban operasional, laba operasi, pendapatan/beban lain, "
        "laba bersih (Rupiah dibulatkan), margin %, perubahan vs pembanding, dan akun pendapatan/HPP/beban "
        "terbesar (akun gaji/tunjangan digabung satu baris untuk owner/SDM, tidak dirinci untuk peran lain). "
        "Gabungan = setelah eliminasi antar CV, plus rincian per CV. Ini angka AKUNTANSI (jurnal), bukan omzet "
        "marketplace."),
    input_schema={"type": "object", "properties": {
        **SKEMA_PERIODE,
        "bandingkan": {"type": "boolean", "description": "Bandingkan dengan periode sebelumnya (bawaan ya)."},
    }, "additionalProperties": False},
    domain="keuangan",
)
async def laba_rugi(ctx, args: dict) -> dict:
    p = periode(args, ctx)
    cv = cv_aktif(ctx)
    kini = await ctx.api("GET", P_LABA_RUGI, params=param_cv(ctx, **{"from": p["dari"], "to": p["sampai"]}))
    bandingkan = (args or {}).get("bandingkan", True) is not False
    lalu = None
    if bandingkan:
        pb = p["pembanding"]
        lalu = await ctx.api("GET", P_LABA_RUGI, params=param_cv(ctx, **{"from": pb["dari"], "to": pb["sampai"]}))
    rk = _ringkas_lr(kini)
    hasil = {"cv": label_cv(cv), "periode": p["label"], "dari": p["dari"], "sampai": p["sampai"], "ringkas": rk}
    if lalu is not None:
        rl = _ringkas_lr(lalu)
        hasil["pembanding"] = {"periode": p["pembanding"]["label"], "ringkas": rl}
        hasil["perubahan"] = {k: perubahan(rk[k], rl[k]) for k in
                              ("pendapatan", "hpp", "laba_kotor", "beban_operasional", "laba_bersih")}
    hasil["akun_terbesar"], catatan = {}, set()
    for kunci, grup, n in (("pendapatan", "revenue", 8), ("hpp", "cogs", 5), ("beban_operasional", "expense", 10)):
        hasil["akun_terbesar"][kunci], c = _akun_terbesar(ctx, kini, grup, n, lalu if bandingkan else None)
        catatan.add(c)
    if catatan - {None}:
        hasil["catatan_gaji"] = (catatan - {None}).pop()
    if cv == "ALL":
        per_cv = {}
        for c in ("DA", "SMU"):
            d, galat = await coba(ctx, "GET", P_LABA_RUGI, param_cv(ctx, c, **{"from": p["dari"], "to": p["sampai"]}))
            per_cv[label_cv(c)] = _ringkas_lr(d) if d else {"galat": galat}
        hasil["per_cv"] = per_cv
        ic = (kini or {}).get("intercompany") or {}
        if ic:
            hasil["catatan_gabungan"] = ("Gabungan sudah mengeliminasi transaksi antar CV; jumlah per CV "
                                         "bisa lebih besar dari angka gabungan.")
    hasil["_sumber"] = "Laporan laba rugi (buku besar)"
    return pangkas(hasil)


# ── neraca ───────────────────────────────────────────────────────────────────
KELOMPOK_ASET = (("1-11", "Kas"), ("1-12", "Bank"), ("1-13", "Piutang usaha"), ("1-14", "Persediaan"),
                 ("1-15", "Pajak dibayar dimuka"), ("1-16", "Uang muka & biaya dibayar dimuka"),
                 ("1-1", "Aset lancar lain"), ("1-2", "Aset tetap (bersih)"), ("", "Aset lain"))
KELOMPOK_LIAB = (("2-11", "Hutang usaha"), ("2-1", "Liabilitas jangka pendek lain"),
                 ("2-2", "Liabilitas jangka panjang"), ("", "Liabilitas lain"))


def _kelompokkan(akun: list, kelompok: tuple) -> list:
    tot: dict = {}
    for a in akun:
        kode = str(a.get("code") or "")
        for awalan, label in kelompok:
            if kode.startswith(awalan):
                tot[label] = tot.get(label, 0) + float(a.get("amount") or 0)
                break
    return [{"kelompok": label, "nilai": rp(tot[label])} for _, label in kelompok if rp(tot.get(label))]


@alat(
    name="neraca_ringkas",
    kind="read",
    label="Membaca neraca",
    description=(
        "Neraca (posisi keuangan) CV aktif per tanggal (bawaan hari ini): total aset, liabilitas, ekuitas "
        "(termasuk laba tahun berjalan), status seimbang, aset per kelompok (kas, bank, piutang, persediaan, "
        "aset tetap, ...), liabilitas per kelompok, serta akun terbesar tiap sisi. Rupiah dibulatkan. "
        "Gabungan = setelah eliminasi hutang-piutang antar CV."),
    input_schema={"type": "object", "properties": {
        "per_tanggal": {"type": "string", "description": "TTTT-BB-HH; kosong = hari ini."},
    }, "additionalProperties": False},
    domain="keuangan",
)
async def neraca_ringkas(ctx, args: dict) -> dict:
    tgl = (args or {}).get("per_tanggal") or hari_ini(ctx).isoformat()
    d_tgl = tanggal_sah(tgl, "per_tanggal")
    d = await ctx.api("GET", P_NERACA, params=param_cv(ctx, as_of=d_tgl.isoformat()))
    t = d.get("totals") or {}
    aset = (d.get("assets") or {}).get("accounts") or []
    liab = (d.get("liabilities") or {}).get("accounts") or []
    ekuitas = (d.get("equity") or {}).get("accounts") or []

    catatan = set()

    def top(rows, n):
        rows, c = saring_akun_gaji(ctx, rows, "name", "amount", kode="code")
        catatan.add(c)
        return [{"kode": a.get("code"), "akun": a.get("name"), "nilai": rp(a.get("amount"))}
                for a in sorted(rows, key=lambda a: -abs(float(a.get("amount") or 0)))[:n]]

    hasil = {
        "cv": label_cv(cv_aktif(ctx)), "per_tanggal": label_tanggal(d_tgl),
        "total": {"aset": rp(t.get("assets")), "liabilitas": rp(t.get("liabilities")),
                  "ekuitas": rp(t.get("equity")), "laba_tahun_berjalan": rp(t.get("current_earnings")),
                  "liabilitas_plus_ekuitas": rp(t.get("liab_plus_equity"))},
        "seimbang": bool(d.get("balanced")), "selisih": rp(t.get("diff")),
        "aset_per_kelompok": _kelompokkan(aset, KELOMPOK_ASET),
        "liabilitas_per_kelompok": _kelompokkan(liab, KELOMPOK_LIAB),
        "aset_terbesar": top(aset, 10), "liabilitas_terbesar": top(liab, 8), "ekuitas": top(ekuitas, 6),
        "rasio": {"liabilitas_per_ekuitas": round(float(t.get("liabilities") or 0) / float(t.get("equity")), 2)
                  if float(t.get("equity") or 0) else None},
    }
    if catatan - {None}:
        hasil["catatan_gaji"] = (catatan - {None}).pop()
    if d.get("orphan_account_lines"):
        hasil["peringatan"] = (f"{len(d['orphan_account_lines'])} akun di jurnal tidak ada di Bagan Akun — "
                               "neraca bisa tidak seimbang; periksa di Portal Keuangan.")
    hasil["_sumber"] = "Neraca (buku besar)"
    return pangkas(hasil)


# ── arus kas ─────────────────────────────────────────────────────────────────
@alat(
    name="arus_kas",
    kind="read",
    label="Membaca arus kas",
    description=(
        "Laporan arus kas metode langsung CV aktif untuk satu bulan (bawaan bulan berjalan) atau rentang "
        "tanggal: kas awal, kas akhir, arus bersih aktivitas operasi/investasi/pendanaan, dan rincian "
        "kategori (masuk, keluar, bersih) per aktivitas. Rupiah dibulatkan, dari buku besar akun kas/bank."),
    input_schema={"type": "object", "properties": dict(SKEMA_PERIODE), "additionalProperties": False},
    domain="keuangan",
)
async def arus_kas(ctx, args: dict) -> dict:
    p = periode(args, ctx)
    d = await ctx.api("GET", P_ARUS_KAS, params=param_cv(ctx, **{"from": p["dari"], "to": p["sampai"]}))
    t = d.get("totals") or {}
    akt = d.get("activities") or {}
    rincian, catatan = {}, set()
    for k, nama in (("operating", "operasi"), ("investing", "investasi"), ("financing", "pendanaan")):
        items = [{**r, "label": r.get("label") or r.get("category")} for r in (akt.get(k) or {}).get("items") or []]
        items, c = saring_akun_gaji(ctx, items, "label", ("inflow", "outflow", "net"))
        catatan.add(c)
        items = sorted(items, key=lambda r: -abs(float(r.get("net") or 0)))[:8]
        rincian[nama] = [{"kategori": r.get("label"), "masuk": rp(r.get("inflow")),
                          "keluar": rp(r.get("outflow")), "bersih": rp(r.get("net"))} for r in items]
    hasil = {
        "cv": label_cv(cv_aktif(ctx)), "periode": p["label"], "dari": p["dari"], "sampai": p["sampai"],
        "ringkas": {"kas_awal": rp(t.get("opening_cash")), "arus_operasi": rp(t.get("operating")),
                    "arus_investasi": rp(t.get("investing")), "arus_pendanaan": rp(t.get("financing")),
                    "kenaikan_bersih": rp(t.get("net_change_in_cash")), "kas_akhir": rp(t.get("closing_cash"))},
        "rincian": rincian,
        "_sumber": "Laporan arus kas (buku besar)",
    }
    if catatan - {None}:
        hasil["catatan_gaji"] = (catatan - {None}).pop()
    return pangkas(hasil)


# ── posisi kas & bank ────────────────────────────────────────────────────────
@alat(
    name="posisi_kas_bank",
    kind="read",
    label="Membaca saldo kas dan bank",
    description=(
        "Saldo terkini rekening kas/bank/dompet aktif milik CV aktif (saldo = buku besar): total keseluruhan dan "
        "per jenis rekening dalam Rupiah, daftar rekening yang bersaldo, dan jumlah rekening bersaldo nol. "
        "Nomor rekening tidak pernah ditampilkan."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    domain="keuangan",
)
async def posisi_kas_bank(ctx, args: dict) -> dict:
    rows = await ctx.api("GET", P_REKENING, params=param_cv(ctx))
    rows = rows if isinstance(rows, list) else (rows or {}).get("items") or []
    jenis_label = {"cash": "Kas", "bank": "Bank", "ewallet": "Dompet digital", "e-wallet": "Dompet digital"}
    rekening, per_jenis = [], {}
    for r in rows:
        jenis = jenis_label.get(str(r.get("type") or "").lower(), str(r.get("type") or "Lainnya").capitalize())
        saldo = rp(r.get("balance"))
        per_jenis[jenis] = per_jenis.get(jenis, 0) + saldo
        rekening.append({"rekening": r.get("name") or r.get("code"), "jenis": jenis,
                         "bank": r.get("bank_name") or None, "cv": label_cv(r.get("entity") or "DA"),
                         "saldo": saldo})
    rekening.sort(key=lambda r: -abs(r["saldo"]))
    bersaldo = [r for r in rekening if r["saldo"]]
    hasil = {"cv": label_cv(cv_aktif(ctx)), "per_tanggal": hari_ini(ctx).isoformat(),
             "total": sum(per_jenis.values()), "per_jenis": [{"jenis": k, "saldo": v} for k, v in per_jenis.items()],
             "jumlah_rekening": len(rekening), "rekening_saldo_nol": len(rekening) - len(bersaldo),
             "rekening": bersaldo[:40],
             "_sumber": "Rekening kas & bank (saldo buku besar)"}
    minus = [r["rekening"] for r in rekening if r["saldo"] < 0]
    if minus:
        hasil["peringatan"] = f"Saldo minus: {', '.join(minus[:5])}. Periksa pencatatan di Portal Keuangan."
    return pangkas(hasil, ("rekening",))


# ── umur piutang & hutang ────────────────────────────────────────────────────
def _umur(d: dict, baris: list, kunci_nama: str, kunci_sisa: str, kunci_nomor: str, jenis_pihak: str, ctx) -> dict:
    ps = samaran(ctx)
    total = rp(d.get("total"))
    kelompok = [{"umur": LABEL_UMUR.get(k, k), "nilai": rp(v), "porsi_pct": persen(v, total)}
                for k, v in (d.get("buckets") or {}).items() if rp(v)]
    per_pihak: dict = {}
    for r in baris:
        nama = r.get(kunci_nama) or "(tanpa nama)"
        kode = ps.code(nama, jenis_pihak) or "-"
        s = per_pihak.setdefault(kode, {"pihak": kode, "sisa": 0, "jumlah_faktur": 0, "telat_terlama_hari": 0})
        s["sisa"] += rp(r.get(kunci_sisa))
        s["jumlah_faktur"] += 1
        s["telat_terlama_hari"] = max(s["telat_terlama_hari"], int(r.get("days_overdue") or 0))
    terlama = sorted(baris, key=lambda r: (-int(r.get("days_overdue") or 0), -float(r.get(kunci_sisa) or 0)))[:10]
    return {
        "total": total, "jumlah_faktur": int(d.get("count") or len(baris)),
        "jatuh_tempo_lewat": rp(sum(float(r.get(kunci_sisa) or 0) for r in baris if int(r.get("days_overdue") or 0) > 0)),
        "per_umur": kelompok,
        "pihak_terbesar": sorted(per_pihak.values(), key=lambda s: -s["sisa"])[:10],
        "faktur_terlama": [{"nomor": r.get(kunci_nomor), "pihak": ps.code(r.get(kunci_nama) or "(tanpa nama)", jenis_pihak),
                            "jatuh_tempo": str(r.get("due_date") or "")[:10] or None,
                            "telat_hari": int(r.get("days_overdue") or 0), "sisa": rp(r.get(kunci_sisa))}
                           for r in terlama],
        "catatan_nama": "Nama pihak disamarkan (kode). Nama lengkap ada di Portal Keuangan.",
    }


@alat(
    name="umur_piutang",
    kind="read",
    label="Membaca umur piutang",
    description=(
        "Umur piutang usaha (faktur penjualan & maklon yang belum lunas) CV aktif: total, jumlah faktur, nilai "
        "yang sudah lewat jatuh tempo, nilai per kelompok umur (belum jatuh tempo, 1–30, 31–60, 61–90, >90 hari), "
        "10 pelanggan dengan sisa terbesar, dan 10 faktur paling lama telat. Nama pelanggan disamarkan menjadi "
        "kode PLG-xxx. CV Sukma = piutang maklon; CV Dewi Aditya = piutang lainnya."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    domain="keuangan",
)
async def umur_piutang(ctx, args: dict) -> dict:
    d = await ctx.api("GET", P_PIUTANG, params=param_cv(ctx))
    hasil = {"cv": label_cv(cv_aktif(ctx)), "per_tanggal": hari_ini(ctx).isoformat(),
             **_umur(d, d.get("details") or [], "customer_name", "amount_due", "invoice_number", "pelanggan", ctx)}
    tanpa = len(((d.get("data_quality") or {}).get("invalid_due_date")) or [])
    if tanpa:
        hasil["peringatan"] = f"{tanpa} faktur tanpa tanggal jatuh tempo yang sah."
    hasil["_sumber"] = "Umur piutang (Portal Keuangan)"
    return pangkas(hasil, ("faktur_terlama", "pihak_terbesar"))


@alat(
    name="umur_hutang",
    kind="read",
    label="Membaca umur hutang",
    description=(
        "Umur hutang usaha CV aktif (tagihan pemasok dan tagihan CMT yang sudah dijurnal): total, nilai lewat "
        "jatuh tempo, nilai per kelompok umur (belum jatuh tempo, 1–30, 31–60, 61–90, >90 hari), 10 pemasok "
        "dengan sisa terbesar, 10 tagihan paling lama telat, dan tagihan yang belum dijurnal (terpisah). Nama "
        "pemasok disamarkan menjadi kode VND-xxx."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    domain="keuangan",
)
async def umur_hutang(ctx, args: dict) -> dict:
    d = await ctx.api("GET", P_HUTANG, params=param_cv(ctx))
    hasil = {"cv": label_cv(cv_aktif(ctx)), "per_tanggal": hari_ini(ctx).isoformat(),
             **_umur(d, d.get("details") or [], "vendor_name", "balance", "number", "vendor", ctx)}
    if rp(d.get("unposted_total")):
        hasil["belum_dijurnal"] = {"jumlah": len(d.get("unposted") or []), "nilai": rp(d.get("unposted_total")),
                                   "catatan": "Tagihan CMT yang belum dijurnal tidak masuk total di atas."}
    hasil["_sumber"] = "Umur hutang (Portal Keuangan)"
    return pangkas(hasil, ("faktur_terlama", "pihak_terbesar"))
