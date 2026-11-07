"""Alat baca Asisten AI — stok & persediaan (Kontrak A). Angka dari endpoint Gudang/Keuangan lewat `ctx.api`.

Sumber:
  * stok per barang + ambang: `GET /api/rahaza/stock-thresholds` (stok kanonik semua lokasi, SSOT
    `core.stock_thresholds`), ringkasan ambang `GET /api/rahaza/stock-thresholds/summary`;
  * stok menipis: `GET /api/rahaza/materials/reorder-alerts` (aturan yang sama dengan notifikasi);
  * nilai persediaan resmi: saldo akun persediaan di neraca (1-14xx), dicocokkan dengan nilai buku pembantu
    aksesoris (`GET /api/acc/valuation`) dan barang jadi (`GET /api/rahaza/finance/reports/fg-inventory-valuation`).
Persediaan bernilai milik CV Dewi Aditya; CV Sukma tidak memegang persediaan bernilai (titipan klien tanpa nilai).
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat
from core.asisten_ai.alat._bantu_laporan import (
    coba, cv_aktif, hari_ini, label_cv, pangkas, param_cv, persen, rp, tanggal_sah,
)

P_AMBANG = "/api/rahaza/stock-thresholds"
P_AMBANG_RINGKAS = "/api/rahaza/stock-thresholds/summary"
P_MENIPIS = "/api/rahaza/materials/reorder-alerts"
P_NERACA = "/api/rahaza/finance/reports/balance-sheet"
P_NILAI_AKSESORIS = "/api/acc/valuation"
P_NILAI_FG = "/api/rahaza/finance/reports/fg-inventory-valuation"

KATEGORI = {"yarn": "bahan", "fabric": "bahan", "kain": "bahan", "benang": "bahan", "interlining": "bahan",
            "accessory": "aksesoris", "packaging": "aksesoris", "fg": "fg"}
LABEL_KATEGORI = {"bahan": "Bahan baku", "aksesoris": "Aksesoris & kemasan", "fg": "Barang jadi", "lain": "Lainnya"}
AKUN_PERSEDIAAN = {"1-1401": "Bahan baku", "1-1402": "Aksesoris (bahan pembantu)", "1-1403": "Barang dalam proses",
                   "1-1404": "Barang jadi"}
CATATAN_CV = ("Persediaan bernilai dicatat di CV Dewi Aditya. CV Sukma (maklon) hanya memegang titipan bahan "
              "klien yang tidak bernilai di buku.")


def kategori_dari(jenis: str) -> str:
    return KATEGORI.get(str(jenis or "").lower(), "lain")


def _qty(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


@alat(
    name="ringkasan_stok",
    kind="read",
    label="Membaca ringkasan stok",
    description=(
        "Ringkasan stok gudang saat ini per kategori (bahan baku, aksesoris & kemasan, barang jadi): jumlah item, "
        "item yang ada stoknya, jumlah stok per satuan, perkiraan nilai (stok × harga satuan master, Rupiah), item "
        "tanpa harga, stok minus, dan item di bawah ambang (menipis/kritis); ditambah 10 item bernilai terbesar dan kondisi ambang stok. "
        "Perkiraan nilai BUKAN nilai buku — untuk nilai resmi pakai nilai_persediaan. Bisa disaring kategori atau "
        "kata kunci kode/nama barang."),
    input_schema={"type": "object", "properties": {
        "kategori": {"type": "string", "enum": ["bahan", "aksesoris", "fg"]},
        "cari": {"type": "string", "description": "Kata kunci kode/nama barang."},
    }, "additionalProperties": False},
    domain="stok",
)
async def ringkasan_stok(ctx, args: dict) -> dict:
    args = args or {}
    params = {"limit": 5000}
    if args.get("kategori"):
        params["type"] = args["kategori"]
    if args.get("cari"):
        params["search"] = str(args["cari"])[:60]
    d = await ctx.api("GET", P_AMBANG, params=params)
    items = (d or {}).get("items") or []
    per: dict = {}
    nilai_item = []
    for it in items:
        kat = kategori_dari(it.get("type"))
        s = per.setdefault(kat, {"kategori": LABEL_KATEGORI[kat], "jumlah_item": 0, "item_ada_stok": 0,
                                 "qty": {}, "perkiraan_nilai": 0, "item_tanpa_harga": 0, "stok_minus": 0,
                                 "di_bawah_ambang": 0})
        q = _qty(it.get("onhand"))
        harga = float(it.get("unit_cost") or 0)
        s["jumlah_item"] += 1
        if q > 0:
            s["item_ada_stok"] += 1
            sat = it.get("unit") or "-"
            s["qty"][sat] = round(s["qty"].get(sat, 0) + q, 2)
            if harga > 0:
                s["perkiraan_nilai"] += q * harga
                nilai_item.append({"kode": it.get("code"), "nama": it.get("name"), "kategori": LABEL_KATEGORI[kat],
                                   "stok": q, "satuan": sat, "nilai": rp(q * harga)})
            else:
                s["item_tanpa_harga"] += 1
        elif q < 0:
            s["stok_minus"] += 1
        if it.get("status") in ("low", "critical"):
            s["di_bawah_ambang"] += 1
    kategori = []
    for kat in ("bahan", "aksesoris", "fg", "lain"):
        if kat in per:
            s = per[kat]
            s["perkiraan_nilai"] = rp(s["perkiraan_nilai"])
            s["qty_per_satuan"] = [{"satuan": k, "qty": v} for k, v in sorted(s.pop("qty").items(),
                                                                                key=lambda kv: -kv[1])[:6]]
            kategori.append(s)
    amb = (d or {}).get("summary") or {}
    hasil = {
        "per_tanggal": hari_ini(ctx).isoformat(),
        "saringan": {k: v for k, v in args.items() if v},
        "per_kategori": kategori,
        "total_perkiraan_nilai": sum(k["perkiraan_nilai"] for k in kategori),
        "item_nilai_terbesar": sorted(nilai_item, key=lambda r: -r["nilai"])[:10],
        "ambang_stok": {"item_dengan_ambang": amb.get("with_threshold"), "item_tanpa_ambang": amb.get("missing_threshold"),
                        "menipis": amb.get("low"), "kritis": amb.get("critical")},
        "catatan": "Perkiraan nilai = stok × harga satuan master barang, bukan nilai buku. Nilai buku resmi ada di neraca (akun persediaan).",
        "_sumber": "Stok gudang (Ambang Stok)",
    }
    if cv_aktif(ctx) != "DA":
        hasil["catatan_cv"] = CATATAN_CV
    return pangkas(hasil, ("item_nilai_terbesar",))


@alat(
    name="stok_menipis",
    kind="read",
    label="Mencari stok menipis",
    description=(
        "Daftar barang yang stoknya di bawah ambang minimum (kritis) atau sudah menyentuh titik pesan ulang "
        "(menipis), urut kekurangan terbesar: kode, nama, kategori, stok, satuan, ambang, kekurangan. Juga "
        "jumlah barang yang BELUM punya ambang (tidak bisa dinilai menipis). Aturan sama dengan notifikasi stok."),
    input_schema={"type": "object", "properties": {
        "kategori": {"type": "string", "enum": ["bahan", "aksesoris", "fg"]},
        "batas": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Jumlah baris (bawaan 30)."},
    }, "additionalProperties": False},
    domain="stok",
)
async def stok_menipis(ctx, args: dict) -> dict:
    args = args or {}
    rows = await ctx.api("GET", P_MENIPIS)
    rows = rows if isinstance(rows, list) else (rows or {}).get("items") or []
    if args.get("kategori"):
        rows = [r for r in rows if kategori_dari(r.get("type")) == args["kategori"]]
    batas = max(1, min(50, int(args.get("batas") or 30)))
    daftar = [{"kode": r.get("code"), "nama": r.get("name"), "kategori": LABEL_KATEGORI[kategori_dari(r.get("type"))],
               "stok": _qty(r.get("current_qty")), "satuan": r.get("unit"), "ambang": _qty(r.get("alert_at")),
               "kurang": _qty(r.get("shortage")),
               "status": "kritis" if r.get("stock_status") == "critical" else "menipis"}
              for r in rows]
    ringkas, galat = await coba(ctx, "GET", P_AMBANG_RINGKAS)
    hasil = {
        "per_tanggal": hari_ini(ctx).isoformat(),
        "jumlah": len(daftar), "kritis": sum(1 for r in daftar if r["status"] == "kritis"),
        "menipis": sum(1 for r in daftar if r["status"] == "menipis"),
        "daftar": daftar[:batas],
        "_sumber": "Ambang stok & titik pesan ulang",
    }
    if ringkas:
        hasil["item_tanpa_ambang"] = ringkas.get("missing_threshold")
        if ringkas.get("missing_threshold"):
            hasil["catatan"] = (f"{ringkas['missing_threshold']} barang belum punya ambang stok, jadi tidak bisa "
                                "dinilai menipis. Ambang diisi di Gudang › Ambang Stok.")
    if len(daftar) > batas:
        hasil["catatan_daftar"] = f"Menampilkan {batas} dari {len(daftar)} barang."
    return pangkas(hasil, ("daftar",))


@alat(
    name="nilai_persediaan",
    kind="read",
    label="Membaca nilai persediaan",
    description=(
        "Nilai persediaan resmi per tanggal (bawaan hari ini): saldo buku besar akun persediaan bahan baku, "
        "aksesoris, barang dalam proses, dan barang jadi (Rupiah) untuk CV aktif, dicocokkan dengan nilai buku "
        "pembantu aksesoris (rata-rata bergerak) dan barang jadi (stok × WAC) beserta selisih dan item yang "
        "belum dinilai."),
    input_schema={"type": "object", "properties": {
        "per_tanggal": {"type": "string", "description": "TTTT-BB-HH; kosong = hari ini."},
    }, "additionalProperties": False},
    domain="stok",
)
async def nilai_persediaan(ctx, args: dict) -> dict:
    tgl = tanggal_sah((args or {}).get("per_tanggal") or hari_ini(ctx).isoformat(), "per_tanggal").isoformat()
    neraca = await ctx.api("GET", P_NERACA, params=param_cv(ctx, as_of=tgl))
    akun = [a for a in ((neraca or {}).get("assets") or {}).get("accounts") or []
            if str(a.get("code") or "").startswith("1-14")]
    buku = [{"kode": a.get("code"), "akun": AKUN_PERSEDIAAN.get(a.get("code"), a.get("name")),
             "nilai": rp(a.get("amount"))} for a in sorted(akun, key=lambda a: str(a.get("code")))]
    total = sum(b["nilai"] for b in buku)
    hasil = {"cv": label_cv(cv_aktif(ctx)), "per_tanggal": tgl, "nilai_buku_besar": buku, "total_buku_besar": total,
             "porsi": [{"akun": b["akun"], "porsi_pct": persen(b["nilai"], total)} for b in buku if total]}
    pembantu = {}
    acc, galat_acc = await coba(ctx, "GET", P_NILAI_AKSESORIS, {"include_zero_stock": "false"})
    if acc:
        t = acc.get("totals") or {}
        gl = next((b["nilai"] for b in buku if b["kode"] == "1-1402"), None)
        pembantu["aksesoris"] = {"nilai": rp(t.get("total_value")), "item_dinilai": t.get("valued_items"),
                                 "item_belum_dinilai": t.get("unvalued_items"),
                                 "selisih_vs_buku_besar": rp(t.get("total_value")) - gl if gl is not None else None,
                                 "per_kategori": [{"kategori": c.get("category"), "nilai": rp(c.get("value"))}
                                                  for c in (acc.get("by_category") or [])[:6]]}
    elif galat_acc:
        pembantu["aksesoris"] = {"galat": galat_acc}
    fg, galat_fg = await coba(ctx, "GET", P_NILAI_FG, {"as_of": tgl})
    if fg:
        t = fg.get("totals") or {}
        pembantu["barang_jadi"] = {"nilai_stok_x_wac": rp(t.get("value")), "saldo_buku_besar": rp(t.get("gl_balance")),
                                   "selisih": rp(t.get("difference")),
                                   "selisih_belum_terjelaskan": rp(t.get("unexplained_difference")),
                                   "pcs_tanpa_biaya": _qty(t.get("uncosted_qty")), "cocok": bool(fg.get("reconciled"))}
    elif galat_fg:
        pembantu["barang_jadi"] = {"galat": galat_fg}
    hasil["buku_pembantu"] = pembantu
    if cv_aktif(ctx) != "DA":
        hasil["catatan_cv"] = CATATAN_CV + " Buku pembantu di atas milik CV Dewi Aditya."
    hasil["_sumber"] = "Neraca akun persediaan + valuasi aksesoris & barang jadi"
    return pangkas(hasil)
