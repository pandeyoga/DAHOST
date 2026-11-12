"""core.merchandiser — SATU sumber angka skill Merchandiser (keputusan owner K-M1..K-M10, 12 Nov 2026).

Masalah owner: bahan dibeli & PO produksi dibuat untuk model yang barang jadinya sudah tidak laku. Modul ini menghitung,
per varian (model × warna × ukuran) lalu dijumlah per warna dan per model:

* **laju jual mingguan** — pcs terjual N minggu terakhir ÷ N (pesanan dihitung omzet menurut `core.ukuran_penjualan`:
  bukan batal, bukan belum bayar, bukan data contoh; dikurangi retur per baris). Pembanding: N minggu sebelumnya (tren);
* **stok perkiraan** (K-M3) — stok barang jadi sistem (`rahaza_material_stock` kategori fg_internal) DIKURANGI penjualan
  sejak hitungan stok terakhir yang belum tercatat keluar lewat scan (scan keluar belum rutin, jadi stok sistem terlalu
  tinggi). Bila scan keluar sudah rutin, selisihnya nol dan stok perkiraan = stok sistem;
* **WIP** — sisa barang dari PO produksi INTERNAL yang masih berjalan, per baris PO (`core.pantau_produksi`):
  dipesan − masuk stok barang jadi (lolos QC) − dibuang (scrap). PO maklon bukan barang DA, tidak dihitung;
* **minggu persediaan** = (stok perkiraan + WIP) ÷ laju; **sell-through** = terjual ÷ (terjual + stok perkiraan);
* **kelas** (K-M1): laris < 3 mgg · sehat 3–8 · perlu awas 8–16 · lambat > 16 · mati = stok ada tetapi 0 terjual
  dalam N minggu · habis = 0 stok & WIP tetapi masih terjual;
* **saran** per kelas + toko terlaris (untuk pindah stok) + warna/ukuran yang tidak laku pada model yang sama.

`cek_rencana` (dipakai alat Asisten & pengaman PO produksi / PR bahan): persediaan SESUDAH tambahan qty → aman /
perlu alasan (model lambat/mati, atau persediaan sesudahnya > batas "perlu awas").

Semua angka menyebut sumber & cakupannya (berapa % penjualan terhubung ke model; penjualan yang belum terhubung
dipetakan di layar Jembatan SKU). Modul ini hanya MEMBACA.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from core import ukuran_penjualan as up

STOK = "rahaza_material_stock"
LEDGER = "rahaza_stock_ledger"
MATERIALS = "rahaza_materials"
MODELS = "rahaza_models"
ORDERS = "marketing_orders"
ACCOUNTS = "marketing_platform_accounts"

AMBANG_BAWAAN = {"laris": 3.0, "sehat": 8.0, "awas": 16.0, "minggu_jual": 4}
KONFIG = "merchandiser_ambang"           # dewi_system_config: {laris, sehat, awas, minggu_jual} — opsional

KELAS = ("laris", "sehat", "awas", "lambat", "mati", "habis", "kosong")
LABEL_KELAS = {"laris": "Laris / kurang stok", "sehat": "Sehat", "awas": "Perlu awas", "lambat": "Lambat",
               "mati": "Mati", "habis": "Habis, masih terjual", "kosong": "Tanpa stok & tanpa jual"}
SARAN = {
    "laris": "Tambah produksi: persediaan lebih pendek dari waktu produksi. Cek bahan cukup sebelum PO.",
    "sehat": "Lanjut sesuai laju jual.",
    "awas": "Tahan PO baru; pantau laju jual mingguan.",
    "lambat": "Stop produksi baru. Dorong penjualan: promo/markdown, pindahkan ke toko yang masih laku, atau bundling "
              "dengan model laris.",
    "mati": "Stop total. Cuci gudang (diskon besar/bundling); jangan beli bahan untuk model ini.",
    "habis": "Stok habis padahal masih terjual: pertimbangkan produksi ulang bila marginnya baik.",
    "kosong": "",
}
SUMBER = ("Penjualan: pesanan marketplace yang dihitung omzet (bukan batal/belum bayar), dikurangi retur. "
          "Stok: stok barang jadi DA di gudang, dikurangi penjualan yang belum tercatat scan keluar sejak hitungan "
          "stok terakhir. WIP: sisa PO produksi internal yang masih berjalan (dipesan − masuk stok − scrap).")
BESAR = 999.0                         # minggu persediaan "tak terhingga" (stok ada, laju 0)


# ── fungsi murni ─────────────────────────────────────────────────────────────
def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def rapikan_ambang(cfg: Optional[dict]) -> dict:
    a = dict(AMBANG_BAWAAN)
    for k in a:
        v = (cfg or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            a[k] = type(AMBANG_BAWAAN[k])(v)
    if not (a["laris"] < a["sehat"] < a["awas"]):
        a.update({k: AMBANG_BAWAAN[k] for k in ("laris", "sehat", "awas")})
    a["minggu_jual"] = max(1, min(26, int(a["minggu_jual"])))
    return a


def kelas_dari(laju: float, stok: float, wip: float, ambang: dict) -> str:
    pipa = max(0.0, stok) + max(0.0, wip)
    if pipa <= 0 and laju <= 0:
        return "kosong"
    if laju <= 0:
        return "mati"
    if pipa <= 0:
        return "habis"
    cover = pipa / laju
    if cover > ambang["awas"]:
        return "lambat"
    if cover > ambang["sehat"]:
        return "awas"
    if cover >= ambang["laris"]:
        return "sehat"
    return "laris"


def metrik(terjual: float, terjual_lalu: float, stok: float, wip: float, minggu: int, ambang: dict) -> dict:
    laju = terjual / minggu if minggu else 0.0
    pipa = max(0.0, stok) + max(0.0, wip)
    cover = (pipa / laju) if laju > 0 else (BESAR if pipa > 0 else 0.0)
    st = terjual / (terjual + max(0.0, stok)) if (terjual + max(0.0, stok)) > 0 else None
    tren = (terjual / terjual_lalu) if terjual_lalu > 0 else None
    k = kelas_dari(laju, stok, wip, ambang)
    return {"terjual": round(terjual, 2), "terjual_sebelumnya": round(terjual_lalu, 2), "laju_mingguan": round(laju, 2),
            "stok_perkiraan": round(max(0.0, stok), 2), "wip": round(max(0.0, wip), 2),
            "minggu_persediaan": round(min(cover, BESAR), 1), "sell_through_persen": None if st is None else round(st * 100, 1),
            "tren": None if tren is None else round(tren, 2), "kelas": k, "kelas_label": LABEL_KELAS[k],
            "saran": SARAN[k]}


# ── pembaca data ─────────────────────────────────────────────────────────────
async def ambang(db) -> dict:
    try:
        from routes.dewi_system_config import get_config_value
        cfg = await get_config_value(db, KONFIG, None)
    except Exception:  # noqa: BLE001 — konfigurasi opsional
        cfg = None
    return rapikan_ambang(cfg if isinstance(cfg, dict) else None)


def _tgl(d: date) -> str:
    return d.isoformat()


async def penjualan(db, dari: str, sampai: str, toko: Optional[str] = None) -> dict:
    """{"per_bahan": {fg_material_id: pcs}, "per_toko": {(model_id, account_id): pcs}, "tanpa_model": {sku: pcs},
    "baris": n, "baris_tertaut": n, "pcs": total, "pcs_tertaut": total}"""
    match = {"$and": [up.filter_dihitung_omzet(), up.filter_tanggal("order_date", dari, sampai)]}
    if toko:
        match["$and"].append({"account_id": toko})
    out = {"per_bahan": defaultdict(float), "per_toko": defaultdict(float), "tanpa_model": defaultdict(float),
           "model_bahan": {}, "baris": 0, "baris_tertaut": 0, "pcs": 0.0, "pcs_tertaut": 0.0}
    proj = {"_id": 0, "account_id": 1, "items.fg_material_id": 1, "items.model_id": 1, "items.seller_sku": 1,
            "items.quantity": 1, "items.qty_returned": 1}
    async for o in db[ORDERS].find(match, proj):
        acc = o.get("account_id") or ""
        for ln in o.get("items") or []:
            if not isinstance(ln, dict):
                continue
            pcs = max(0.0, _f(ln.get("quantity")) - _f(ln.get("qty_returned")))
            out["baris"] += 1
            out["pcs"] += pcs
            fg, model = ln.get("fg_material_id"), ln.get("model_id")
            if fg and model:
                out["baris_tertaut"] += 1
                out["pcs_tertaut"] += pcs
                out["per_bahan"][fg] += pcs
                out["model_bahan"][fg] = model
                out["per_toko"][(model, acc)] += pcs
            else:
                out["tanpa_model"][str(ln.get("seller_sku") or "(tanpa SKU)")] += pcs
    return out


async def bahan_fg(db) -> Dict[str, dict]:
    """Master barang jadi: {material_id: {model_id, variant_id, warna, ukuran, sku, hpp}}."""
    out = {}
    async for m in db[MATERIALS].find({"type": "fg"}, {"_id": 0, "id": 1, "model_id": 1, "variant_id": 1, "sku": 1,
                                                       "code": 1, "color_name": 1, "color": 1, "size_code": 1,
                                                       "hpp": 1, "wac_last": 1, "unit_cost": 1}):
        hpp = next((_f(m.get(k)) for k in ("wac_last", "unit_cost", "hpp") if _f(m.get(k)) > 0), 0.0)
        out[m["id"]] = {"model_id": m.get("model_id"), "variant_id": m.get("variant_id"),
                        "sku": m.get("sku") or m.get("code") or "", "warna": m.get("color_name") or m.get("color") or "",
                        "ukuran": m.get("size_code") or "", "hpp": hpp}
    return out


async def stok_fg(db) -> Dict[str, float]:
    out: Dict[str, float] = defaultdict(float)
    async for s in db[STOK].find({"inventory_category": "fg_internal"}, {"_id": 0, "material_id": 1, "qty": 1}):
        if s.get("material_id"):
            out[s["material_id"]] += _f(s.get("qty"))
    return out


async def keluar_belum_tercatat(db, bahan: Iterable[str], hari_ini: date) -> Dict[str, float]:
    """Penjualan sejak hitungan stok terakhir per barang jadi yang BELUM tercatat keluar (scan keluar).

    Hitungan stok terakhir = mutasi `add`/`adjust` saldo awal/opname terbaru barang itu di ledger; keluar tercatat =
    mutasi `issue` sesudahnya. Hasil ≥ 0."""
    bahan = [b for b in bahan if b]
    if not bahan:
        return {}
    hitung: Dict[str, datetime] = {}
    keluar_sesudah: Dict[str, float] = defaultdict(float)
    rows = await db[LEDGER].find({"material_id": {"$in": bahan}},
                                 {"_id": 0, "material_id": 1, "op": 1, "delta": 1, "created_at": 1,
                                  "ref": 1}).to_list(200_000)
    for r in rows:
        if _hitungan_stok(r):
            t = _waktu(r.get("created_at"))
            if t and (r["material_id"] not in hitung or t > hitung[r["material_id"]]):
                hitung[r["material_id"]] = t
    for r in rows:
        t = _waktu(r.get("created_at"))
        mulai = hitung.get(r["material_id"])
        if r.get("op") == "issue" and _keluar_jual(r) and t and mulai and t >= mulai:
            keluar_sesudah[r["material_id"]] += abs(_f(r.get("delta")))
    # penjualan per barang SEJAK tanggal hitungannya sendiri (dikelompokkan per tanggal: saldo awal cutoff dan
    # opname biasanya massal, jadi hanya beberapa kueri)
    per_tanggal: Dict[str, List[str]] = defaultdict(list)
    for m, t in hitung.items():
        per_tanggal[_tgl(t.astimezone(timezone(timedelta(hours=7))).date())].append(m)
    out: Dict[str, float] = {}
    for tgl, ms in per_tanggal.items():
        if tgl > hari_ini.isoformat():
            continue
        jual = await penjualan(db, tgl, hari_ini.isoformat())
        for m in ms:
            out[m] = max(0.0, jual["per_bahan"].get(m, 0.0) - keluar_sesudah.get(m, 0.0))
    return out


def _ref(r: dict) -> dict:
    ref = r.get("ref")
    return ref if isinstance(ref, dict) else {"type": str(ref or "")}


def _hitungan_stok(r: dict) -> bool:
    """Mutasi yang menetapkan jumlah fisik: saldo awal go-live atau opname."""
    ref = _ref(r)
    jenis = f"{ref.get('type') or ''} {ref.get('source') or ''}".lower()
    return r.get("op") in ("add", "adjust") and ("opening" in jenis or "opname" in jenis)


def _keluar_jual(r: dict) -> bool:
    """Mutasi keluar karena penjualan (scan keluar marketplace)."""
    jenis = f"{_ref(r).get('type') or ''}".lower()
    return "scan_out" in jenis or "scan-out" in jenis or "penjualan" in jenis


def _waktu(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def wip_internal(db) -> Dict[str, float]:
    """{variant_id: pcs} sisa PO produksi INTERNAL yang masih berjalan (SSOT angka: core.pantau_produksi)."""
    from core import pantau_produksi as pp
    pos = await pp.load_pos(db, pp.BT_INTERNAL, running=True)
    if not pos:
        return {}
    lines = await pp.po_lines(db, pos)
    ids = [ln["po_item_id"] for ln in lines if ln.get("po_item_id")]
    var = {}
    async for it in db.po_items.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "rahaza_variant_id": 1, "variant_id": 1}):
        var[it["id"]] = it.get("rahaza_variant_id") or it.get("variant_id")
    out: Dict[str, float] = defaultdict(float)
    for ln in lines:
        v = var.get(ln.get("po_item_id"))
        if not v:
            continue
        sisa = max(0, int(ln.get("ordered") or 0) - int(ln.get("final") or 0) - int(ln.get("scrap") or 0))
        out[v] += sisa
    return out


async def nama_model(db, ids: Iterable[str]) -> Dict[str, dict]:
    ids = [i for i in ids if i]
    out = {}
    async for m in db[MODELS].find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "hpp": 1}):
        out[m["id"]] = {"kode": m.get("code") or "", "nama": m.get("name") or "", "hpp": _f(m.get("hpp"))}
    return out


async def nama_toko(db) -> Dict[str, str]:
    out = {}
    async for a in db[ACCOUNTS].find({}, {"_id": 0, "id": 1, "account_name": 1, "name": 1, "code": 1}):
        out[a.get("id")] = a.get("account_name") or a.get("name") or a.get("code") or a.get("id")
    return out


# ── analisa ──────────────────────────────────────────────────────────────────
async def analisa(db, *, hari_ini: date, minggu: Optional[int] = None, toko: Optional[str] = None,
                  tingkat: str = "model", model_id: Optional[str] = None) -> dict:
    """Baris per model | warna | varian + ringkasan per kelas + cakupan data + sumber."""
    amb = await ambang(db)
    n = int(minggu or amb["minggu_jual"])
    sampai = hari_ini
    dari = sampai - timedelta(days=7 * n - 1)
    dari_lalu = dari - timedelta(days=7 * n)
    sampai_lalu = dari - timedelta(days=1)
    jual = await penjualan(db, _tgl(dari), _tgl(sampai), toko)
    jual_lalu = await penjualan(db, _tgl(dari_lalu), _tgl(sampai_lalu), toko)
    master = await bahan_fg(db)
    stok = await stok_fg(db)
    belum = await keluar_belum_tercatat(db, list(stok), hari_ini)
    wip_v = await wip_internal(db)

    # per varian (barang jadi)
    var_ke_bahan = {m.get("variant_id"): mid for mid, m in master.items() if m.get("variant_id")}
    per_bahan: Dict[str, dict] = {}
    semua = set(jual["per_bahan"]) | set(jual_lalu["per_bahan"]) | set(stok) | \
        {var_ke_bahan[v] for v in wip_v if v in var_ke_bahan}
    for mid in semua:
        m = master.get(mid) or {}
        if model_id and m.get("model_id") != model_id:
            continue
        sp = max(0.0, stok.get(mid, 0.0) - belum.get(mid, 0.0))
        per_bahan[mid] = {"bahan_id": mid, "model_id": m.get("model_id") or jual["model_bahan"].get(mid),
                          "variant_id": m.get("variant_id"), "sku": m.get("sku", ""), "warna": m.get("warna", ""),
                          "ukuran": m.get("ukuran", ""), "hpp": m.get("hpp", 0.0),
                          "terjual": jual["per_bahan"].get(mid, 0.0), "terjual_lalu": jual_lalu["per_bahan"].get(mid, 0.0),
                          "stok_sistem": stok.get(mid, 0.0), "stok": sp,
                          "wip": wip_v.get(m.get("variant_id"), 0.0) if m.get("variant_id") else 0.0}

    def kunci(b):
        if tingkat == "varian":
            return b["bahan_id"]
        if tingkat == "warna":
            return f"{b['model_id']}|{b['warna']}"
        return b["model_id"]

    grup: Dict[str, dict] = {}
    for b in per_bahan.values():
        if not b["model_id"]:
            continue
        g = grup.setdefault(kunci(b), {"model_id": b["model_id"], "warna": b["warna"] if tingkat != "model" else "",
                                       "ukuran": b["ukuran"] if tingkat == "varian" else "",
                                       "sku": b["sku"] if tingkat == "varian" else "",
                                       "terjual": 0.0, "terjual_lalu": 0.0, "stok": 0.0, "stok_sistem": 0.0, "wip": 0.0,
                                       "nilai_stok": 0.0, "varian": 0})
        for k in ("terjual", "terjual_lalu", "stok", "stok_sistem", "wip"):
            g[k] += b[k]
        g["nilai_stok"] += b["stok"] * (b["hpp"] or 0.0)
        g["varian"] += 1
    nm = await nama_model(db, {g["model_id"] for g in grup.values()})
    tk = await nama_toko(db)
    toko_terlaris: Dict[str, list] = defaultdict(list)
    for (mid, acc), pcs in jual["per_toko"].items():
        toko_terlaris[mid].append((pcs, acc))
    baris = []
    for g in grup.values():
        mt = metrik(g["terjual"], g["terjual_lalu"], g["stok"], g["wip"], n, amb)
        info = nm.get(g["model_id"]) or {}
        nilai = g["nilai_stok"] or (g["stok"] * info.get("hpp", 0.0))
        tt = sorted(toko_terlaris.get(g["model_id"], []), reverse=True)[:3]
        baris.append({"model_id": g["model_id"], "kode": info.get("kode", ""), "nama": info.get("nama", ""),
                      "warna": g["warna"], "ukuran": g["ukuran"], "sku": g["sku"], "varian": g["varian"],
                      "stok_sistem": round(g["stok_sistem"], 2), "nilai_stok_hpp": round(nilai, 0),
                      "toko_terlaris": [{"toko": tk.get(a, a), "pcs": round(p, 2)} for p, a in tt], **mt})
    urut = {k: i for i, k in enumerate(("mati", "lambat", "awas", "laris", "habis", "sehat", "kosong"))}
    baris.sort(key=lambda r: (urut[r["kelas"]], -r["nilai_stok_hpp"], -r["stok_perkiraan"], r["kode"]))
    ringkas: Dict[str, dict] = {k: {"label": LABEL_KELAS[k], "baris": 0, "stok": 0.0, "wip": 0.0, "nilai_stok_hpp": 0.0}
                                for k in KELAS}
    for r in baris:
        s = ringkas[r["kelas"]]
        s["baris"] += 1
        s["stok"] += r["stok_perkiraan"]
        s["wip"] += r["wip"]
        s["nilai_stok_hpp"] += r["nilai_stok_hpp"]
    tanpa = sorted(jual["tanpa_model"].items(), key=lambda kv: -kv[1])
    cakupan = {
        "baris_penjualan": jual["baris"], "baris_tertaut": jual["baris_tertaut"],
        "persen_pcs_tertaut": round(100 * jual["pcs_tertaut"] / jual["pcs"], 1) if jual["pcs"] else None,
        "pcs_tanpa_model": round(sum(v for _k, v in tanpa), 2),
        "sku_tanpa_model": [{"sku": k, "pcs": round(v, 2)} for k, v in tanpa[:15]],
        "penjualan_belum_scan_keluar_pcs": round(sum(belum.values()), 2),
        "stok_sistem_pcs": round(sum(stok.values()), 2),
        "catatan": [],
    }
    if cakupan["penjualan_belum_scan_keluar_pcs"] > 0:
        cakupan["catatan"].append(
            f"{cakupan['penjualan_belum_scan_keluar_pcs']:.0f} pcs terjual sejak hitungan stok terakhir belum tercatat "
            "scan keluar — stok memakai PERKIRAAN (stok sistem dikurangi penjualan itu).")
    if tanpa:
        cakupan["catatan"].append(f"{cakupan['pcs_tanpa_model']:.0f} pcs penjualan belum terhubung ke model; petakan di "
                                  "layar Jembatan SKU supaya ikut terhitung.")
    return {"periode": {"dari": _tgl(dari), "sampai": _tgl(sampai), "minggu": n,
                        "pembanding": {"dari": _tgl(dari_lalu), "sampai": _tgl(sampai_lalu)}},
            "ambang": amb, "tingkat": tingkat, "toko": toko, "ringkasan": ringkas, "baris": baris, "cakupan": cakupan,
            "sumber": SUMBER}


async def cek_rencana(db, *, hari_ini: date, model_id: str, qty: float, variant_id: Optional[str] = None) -> dict:
    """Persediaan sesudah tambahan `qty` pcs untuk satu model (atau satu varian) → keputusan."""
    a = await analisa(db, hari_ini=hari_ini, tingkat="varian" if variant_id else "model", model_id=model_id)
    amb = a["ambang"]
    rows = [r for r in a["baris"] if r["model_id"] == model_id]
    if variant_id:
        master = await bahan_fg(db)
        sku = next((m["sku"] for m in master.values() if m.get("variant_id") == variant_id), None)
        rows = [r for r in rows if r.get("sku") == sku] if sku else []
    terjual = sum(r["terjual"] for r in rows)
    stok = sum(r["stok_perkiraan"] for r in rows)
    wip = sum(r["wip"] for r in rows)
    n = a["periode"]["minggu"]
    k = keputusan(terjual, sum(r["terjual_sebelumnya"] for r in rows), stok, wip, qty, n, amb)
    return {"model_id": model_id, "variant_id": variant_id, "qty": _f(qty), **k,
            "periode": a["periode"], "cakupan": {x: a["cakupan"][x] for x in ("persen_pcs_tertaut",
                                                                               "penjualan_belum_scan_keluar_pcs")},
            "sumber": SUMBER}


def keputusan(terjual: float, terjual_lalu: float, stok: float, wip: float, qty: float, n: int, amb: dict) -> dict:
    """Fungsi murni: rencana tambahan `qty` pcs → {sekarang, sesudah, keputusan aman|perlu_alasan, alasan[]}.

    Model BARU (belum pernah terjual, tanpa stok & WIP) tidak ditahan — peluncuran produk baru bukan "barang tidak
    laku". Perlu alasan bila model sekarang lambat/mati, atau persediaan SESUDAH tambahan melewati batas perlu awas."""
    sekarang = metrik(terjual, terjual_lalu, stok, wip, n, amb)
    sesudah = metrik(terjual, terjual_lalu, stok, wip + max(0.0, _f(qty)), n, amb)
    if sekarang["kelas"] == "kosong" and terjual_lalu <= 0:
        return {"sekarang": sekarang, "sesudah": sesudah, "keputusan": "aman", "baru": True,
                "alasan": ["model baru: belum ada penjualan maupun stok, jadi belum bisa dinilai"]}
    alasan = []
    if sekarang["kelas"] in ("lambat", "mati"):
        alasan.append(f"model ini {sekarang['kelas_label'].lower()} (persediaan "
                      f"{_mgg(sekarang['minggu_persediaan'])}, laju {sekarang['laju_mingguan']:g} pcs/minggu)")
    if sesudah["minggu_persediaan"] > amb["awas"]:
        alasan.append(f"sesudah tambahan {_f(qty):.0f} pcs persediaan menjadi {_mgg(sesudah['minggu_persediaan'])} "
                      f"(batas {amb['awas']:.0f} minggu)")
    return {"sekarang": sekarang, "sesudah": sesudah, "keputusan": "perlu_alasan" if alasan else "aman",
            "baru": False, "alasan": alasan}


def _mgg(v: float) -> str:
    return "tak terbatas (tidak terjual)" if v >= BESAR else f"{v:g} minggu"


# ── Pengaman PO produksi & pembelian bahan (M2, keputusan owner K-M2) ────────
STATUS_ALASAN = 428                     # sama dengan pola "alasan wajib" kelebihan qty (core.over_qty)
MIN_ALASAN = 10
KUNCI_ALASAN = "alasan_merchandiser"    # isian body yang membawa alasan
LANGKAH = {"po_produksi": "PO produksi", "pr_bahan": "permintaan pembelian bahan",
           "po_bahan": "PO pembelian bahan", "pr_aksesoris": "permintaan pembelian aksesoris"}
KELAS_TAHAN = ("lambat", "mati")


async def model_dari_item(db, items: Iterable[dict]) -> Dict[str, float]:
    """{model_id: qty} dari baris PO produksi (model_id langsung, atau varian/SKU master → modelnya)."""
    out: Dict[str, float] = defaultdict(float)
    cari = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        q = _f(it.get("qty") if it.get("qty") is not None else it.get("qty_ordered"))
        if q <= 0:
            continue
        if it.get("model_id"):
            out[it["model_id"]] += q
        else:
            cari.append((it, q))
    for it, q in cari:
        vid = it.get("rahaza_variant_id") or it.get("variant_id")
        filt = {"id": vid} if vid else ({"sku": it["sku"]} if it.get("sku") else None)
        if not filt:
            continue
        v = await db.rahaza_model_variants.find_one(filt, {"_id": 0, "model_id": 1})
        if v and v.get("model_id"):
            out[v["model_id"]] += q
    return dict(out)


async def periksa_produksi(db, per_model: Dict[str, float], *, hari_ini: date,
                           analisa_siap: Optional[dict] = None) -> List[dict]:
    """Model dalam rencana produksi yang PERLU ALASAN (lambat/mati, atau persediaan sesudahnya > batas)."""
    per_model = {m: q for m, q in (per_model or {}).items() if m and q > 0}
    if not per_model:
        return []
    a = analisa_siap or await analisa(db, hari_ini=hari_ini)
    amb, n = a["ambang"], a["periode"]["minggu"]
    rows = {r["model_id"]: r for r in a["baris"]}
    nm = await nama_model(db, per_model)
    out = []
    for mid, q in sorted(per_model.items()):
        r = rows.get(mid) or {}
        k = keputusan(r.get("terjual", 0.0), r.get("terjual_sebelumnya", 0.0), r.get("stok_perkiraan", 0.0),
                      r.get("wip", 0.0), q, n, amb)
        if k["keputusan"] == "perlu_alasan":
            info = nm.get(mid) or {}
            out.append({"model_id": mid, "kode": info.get("kode") or r.get("kode", ""), "nama": info.get("nama")
                        or r.get("nama", ""), "qty": q, "kelas": k["sekarang"]["kelas"],
                        "minggu_sekarang": k["sekarang"]["minggu_persediaan"],
                        "minggu_sesudah": k["sesudah"]["minggu_persediaan"], "alasan": k["alasan"]})
    return out


async def periksa_bahan(db, material_ids: Iterable[str], *, hari_ini: date,
                        analisa_siap: Optional[dict] = None) -> List[dict]:
    """Bahan yang hanya dipakai (menurut BOM) model lambat/mati — membelinya berarti menambah barang tidak laku.
    Bahan yang tidak ada di BOM mana pun (bahan umum) atau dipakai minimal satu model yang masih laku tidak ditahan."""
    ids = sorted({m for m in material_ids or [] if m})
    if not ids:
        return []
    pemakai: Dict[str, set] = defaultdict(set)
    async for b in db.rahaza_boms.find({"materials.material_id": {"$in": ids}, "is_active": {"$ne": False}},
                                       {"_id": 0, "model_id": 1, "materials.material_id": 1}):
        for m in b.get("materials") or []:
            if isinstance(m, dict) and m.get("material_id") in ids and b.get("model_id"):
                pemakai[m["material_id"]].add(b["model_id"])
    if not pemakai:
        return []
    a = analisa_siap or await analisa(db, hari_ini=hari_ini)
    kelas = {r["model_id"]: r["kelas"] for r in a["baris"]}
    rows = {r["model_id"]: r for r in a["baris"]}
    nama = {}
    async for m in db[MATERIALS].find({"id": {"$in": list(pemakai)}}, {"_id": 0, "id": 1, "code": 1, "name": 1}):
        nama[m["id"]] = f"{m.get('code') or ''} {m.get('name') or ''}".strip()
    out = []
    for mid, models in sorted(pemakai.items()):
        ks = {mm: kelas.get(mm, "kosong") for mm in models}
        bernilai = [mm for mm, k in ks.items() if k != "kosong"]
        if not bernilai or any(ks[mm] not in KELAS_TAHAN for mm in bernilai):
            continue
        contoh = sorted(bernilai, key=lambda mm: -(rows.get(mm) or {}).get("stok_perkiraan", 0))[:5]
        out.append({"material_id": mid, "nama": nama.get(mid, mid), "model": [
            {"model_id": mm, "kode": (rows.get(mm) or {}).get("kode", ""), "kelas": ks[mm],
             "minggu_persediaan": (rows.get(mm) or {}).get("minggu_persediaan")} for mm in contoh],
            "alasan": ["semua model yang memakai bahan ini (menurut BOM) lambat atau mati"]})
    return out


def pesan(temuan: List[dict], langkah: str) -> str:
    bagian = []
    for t in temuan[:5]:
        if "material_id" in t:
            mod = ", ".join(f"{m['kode']} ({LABEL_KELAS.get(m['kelas'], m['kelas']).lower()})" for m in t["model"])
            bagian.append(f"{t['nama']}: hanya dipakai {mod}")
        else:
            bagian.append(f"{t['kode']} {t['nama']} +{t['qty']:.0f} pcs: " + "; ".join(t["alasan"]))
    lebih = f" dan {len(temuan) - 5} lainnya" if len(temuan) > 5 else ""
    return (f"Pengaman Merchandiser: {LANGKAH.get(langkah, langkah)} ini menambah persediaan yang sulit "
            "terjual — " + " · ".join(bagian) + lebih +
            f". Isi alasan (minimal {MIN_ALASAN} huruf) untuk tetap melanjutkan; alasan tercatat di dokumen.")


def wajib_alasan(temuan: List[dict], alasan: Any, langkah: str) -> str:
    """Alasan yang dirapikan; HTTP 428 bila ada temuan tanpa alasan yang cukup (pola sama dengan core.over_qty)."""
    from fastapi import HTTPException
    teks = str(alasan or "").strip()[:1000]
    if temuan and len(teks) < MIN_ALASAN:
        raise HTTPException(STATUS_ALASAN, pesan(temuan, langkah))
    return teks


def jejak(langkah: str, temuan: List[dict], alasan: str, user: dict) -> dict:
    """Satu entri `merchandiser_events`: siapa, kapan, alasan, model/bahan yang ditahan."""
    return {"langkah": langkah, "alasan": alasan, "temuan": temuan[:20],
            "oleh": {"id": (user or {}).get("id"), "nama": (user or {}).get("name") or (user or {}).get("email")},
            "pada": datetime.now(timezone.utc).isoformat()}


async def catat(db, koleksi: str, doc_id: str, langkah: str, temuan: List[dict], alasan: str, user: dict) -> None:
    """Tambahkan jejak ke dokumen yang sudah tersimpan (`$push merchandiser_events`)."""
    if not temuan or not doc_id:
        return
    await db[koleksi].update_one({"id": doc_id},
                                 {"$push": {"merchandiser_events": jejak(langkah, temuan, alasan, user)}})


def bahan_baru(lama: Iterable[dict], baru: Iterable[dict], kunci: str = "material_id") -> List[str]:
    """Id bahan yang muncul di daftar baris BARU tetapi tidak ada di daftar lama (ubah draf = tambah bahan)."""
    ada = {(x or {}).get(kunci) for x in lama or [] if isinstance(x, dict)}
    return sorted({(x or {}).get(kunci) for x in baru or [] if isinstance(x, dict)} - ada - {None, ""})


async def periksa(db, *, hari_ini: date, per_model: Optional[dict] = None,
                  material_ids: Optional[Iterable[str]] = None) -> List[dict]:
    """Temuan pengaman untuk rencana produksi (`per_model` {model_id: qty}) dan/atau pembelian bahan."""
    temuan: List[dict] = []
    a = None
    if per_model:
        a = await analisa(db, hari_ini=hari_ini)
        temuan += await periksa_produksi(db, per_model, hari_ini=hari_ini, analisa_siap=a)
    if material_ids:
        temuan += await periksa_bahan(db, material_ids, hari_ini=hari_ini, analisa_siap=a)
    return temuan


async def jaga(db, *, langkah: str, alasan: Any, user: dict, hari_ini: date, per_model: Optional[dict] = None,
               material_ids: Optional[Iterable[str]] = None) -> tuple:
    """Satu pintu untuk route: (temuan, alasan_rapi). Melempar 428 bila perlu alasan dan alasan belum cukup."""
    temuan = await periksa(db, hari_ini=hari_ini, per_model=per_model, material_ids=material_ids)
    return temuan, wajib_alasan(temuan, alasan, langkah)


# ── Jejak pengaman (M3, laporan Senin & layar) ───────────────────────────────
DOK_PENGAMAN = (  # koleksi, kolom nomor, label, menu layar
    ("production_pos", "po_number", "PO produksi", "prod-pos-internal"),
    ("dewi_procurement_requests", "request_number", "Permintaan pengadaan", "proc-requests"),
    ("rahaza_purchase_orders", "po_number", "PO pembelian", "proc-purchase-orders"),
    ("acc_purchase_requests", "pr_number", "PR aksesoris", "proc-accessory-pr"),
)


async def jejak_pengaman(db, *, sejak: datetime, batas: int = 100) -> List[dict]:
    """Dokumen yang LOLOS pengaman dengan alasan sejak `sejak` (terbaru dulu): siapa, kapan, alasan, model/bahan."""
    batas_iso = sejak.astimezone(timezone.utc).isoformat() if sejak.tzinfo else sejak.isoformat()
    out: List[dict] = []
    for kol, nomor, label, menu in DOK_PENGAMAN:
        async for d in db[kol].find({"merchandiser_events": {"$elemMatch": {"pada": {"$gte": batas_iso}}}},
                                    {"_id": 0, "id": 1, nomor: 1, "merchandiser_events": 1}):
            for ev in d.get("merchandiser_events") or []:
                if str(ev.get("pada") or "") < batas_iso:
                    continue
                isi = [t.get("kode") or t.get("nama") or "" for t in ev.get("temuan") or []]
                out.append({"jenis": label, "menu": menu, "dokumen_id": d.get("id"), "nomor": d.get(nomor) or "",
                            "langkah": ev.get("langkah"), "alasan": ev.get("alasan") or "",
                            "oleh": (ev.get("oleh") or {}).get("nama") or "", "pada": ev.get("pada"),
                            "barang": [x for x in isi if x][:10]})
    out.sort(key=lambda r: str(r["pada"]), reverse=True)
    return out[:batas]
