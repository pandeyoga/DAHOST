"""Alat TINDAKAN risiko MENENGAH (Asisten AI Tahap C, agen harga — 8 Nov 2026). Kontrak D, ``risiko="menengah"``.

Semua lewat kartu konfirmasi DUA LANGKAH dengan alasan wajib (kartu + dialog alasan + konfirmasi kedua):

* ``ubah_harga_jual``            — harga jual (dan harga coret) item katalog toko, banyak SKU sekaligus
  (= ubah item di layar Katalog, ``PUT /api/marketing/catalogs/{katalog}/items/{item}``); kartu memuat
  lama → baru dan margin terhadap HPP bila HPP diketahui. Dibalikkan = harga lama dipulihkan bila belum
  diubah orang lain. Setiap perubahan masuk riwayat harga (Jejak Perubahan Marketing).
* ``atur_promo``                 — buat / ubah / akhiri kampanye diskon (= layar Diskon,
  ``/api/marketing/discounts``). Dibalikkan = promo baru dihapus (atau diakhiri hari ini bila pengguna
  tidak boleh menghapus), ubahan dikembalikan.
* ``ubah_tenggat_po_produksi``   — tenggat produksi / tenggat kirim PO (``PUT /api/production-pos/{id}``,
  hanya kolom tanggal). PO maklon yang sudah dikonfirmasi DITOLAK: mengubahnya menyegarkan jadwal piutang/
  hutang klien (keputusan owner: urusan keuangan tidak lewat AI).
* ``buat_draf_po_produksi``      — DRAF PO produksi internal (``POST /api/production-pos``). Tidak pernah
  mengonfirmasi atau merilis PO. Dibalikkan = draf dihapus selama masih draf utuh.
* ``ubah_titik_pesan_ulang``     — ambang stok minimum / titik pesan ulang barang (bahan, aksesoris, barang jadi)
  lewat layar Ambang Stok (``POST /api/rahaza/stock-thresholds/bulk``). TIDAK PERNAH mengubah jumlah stok.
* ``tutup_buka_bulan_marketing`` — tutup / buka periode bulanan toko (Siklus Marketing,
  ``POST /api/marketing/periods/lock``). Ini kunci periode MARKETING, bukan kunci periode akuntansi.

Alat BACA pendukung: ``riwayat_harga`` (riwayat harga jual dari Jejak Perubahan + harga sekarang) dan
``daftar_promo`` (kampanye diskon yang bisa dipilih).

Aturan (desain §4, Kontrak D): ``siapkan`` hanya membaca; semua tulisan lewat ``ctx.api`` dengan token pengguna
(izin, lingkup toko, kunci periode = sama dengan layar); Gabungan (CV "ALL") ditolak untuk tulisan; banyak
tulisan → bila satu gagal yang sudah tertulis dikembalikan; pembalikan menolak (409) bila data sudah diubah
orang lain sesudah tindakan.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from core import ukuran_penjualan as U
from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat import tindakan_pemasaran as TP
from core.asisten_ai.alat_base import AlatError, alat, tindakan

TANGGAL = TP.TANGGAL
BULAN = TP.BULAN
ALASAN_WAJIB = {"type": "string", "minLength": 5, "maxLength": 300,
                "description": "Alasan perubahan dari percakapan (wajib). Masuk jejak bersama tanda 'Asisten AI'; "
                               "pengguna bisa mengubahnya di kartu."}
rp = TP.rp


# ══════════════════════════════════════════════════════════════════════════════
# Pembantu bersama
# ══════════════════════════════════════════════════════════════════════════════
def _q(v: Any) -> str:
    """Angka Indonesia ≤ 2 desimal: 1234.5 → '1.234,5'."""
    x = round(float(v or 0), 2)
    s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(v: Any) -> str:
    return f"{float(v):.1f}".replace(".", ",") + "%"


def _tgl(iso: Optional[str]) -> str:
    iso = str(iso or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        return "—"
    return TP.label_tanggal(iso)


def _alasan(args: dict) -> str:
    """Alasan wajib (bisa diubah pengguna di kartu, jadi diperiksa ulang di sini, bukan hanya oleh skema)."""
    a = str((args or {}).get("alasan") or "").strip()
    if len(a) < 5:
        raise AlatError(400, "Tulis alasan perubahan (minimal 5 karakter); alasan ini masuk jejak perubahan.")
    return a[:300]


def _ubah_alasan(args: dict) -> dict:
    return {"kunci": "alasan", "label": "Alasan (masuk jejak)", "jenis": "teks", "nilai": args.get("alasan") or ""}


def _tanggal_maju(ctx, iso: str, nama: str, *, hari_maks: int = 730) -> date:
    d = TP._tanggal_sah(iso, nama)
    if d < B.hari_ini(ctx):
        raise AlatError(400, f"{nama} {TP.label_tanggal(iso)} sudah lewat; pilih hari ini atau sesudahnya.")
    if d > B.hari_ini(ctx) + timedelta(days=hari_maks):
        raise AlatError(400, f"{nama} terlalu jauh (paling lama {hari_maks // 365} tahun dari hari ini).")
    return d


def _bulat(v: Any, nd: int = 4) -> float:
    try:
        return round(float(v or 0), nd)
    except (TypeError, ValueError):
        return 0.0


def _gagal_balik(apa: str, gagal: List[str]) -> AlatError:
    return AlatError(502, f"Sebagian {apa} gagal dikembalikan: " + "; ".join(gagal[:5])
                     + ". Yang lain sudah kembali seperti semula; periksa layarnya.")


# ══════════════════════════════════════════════════════════════════════════════
# 1. HARGA JUAL KATALOG
# ══════════════════════════════════════════════════════════════════════════════
P_CARI_ITEM = "/api/marketing/catalog-items/search"
P_LOG = "/api/marketing/change-log"


def _cek_penulis_katalog(ctx) -> None:
    """Pra-cek ramah — aturan yang SAMA dengan PUT item katalog (endpoint tetap penjaga sebenarnya)."""
    from routes.marketing_catalog_items import CATALOG_WRITER_ROLES
    from routes.shared import can_act
    if not can_act(ctx.user, "toko.manage", "pricing.approve", legacy_roles=CATALOG_WRITER_ROLES):
        raise AlatError(403, "Akun Anda tidak boleh mengubah harga jual katalog: itu wewenang tim Marketing pengelola "
                             "toko (atau izin 'kelola toko'/'setujui harga'). Asisten AI hanya bisa melakukan apa yang "
                             "bisa Anda lakukan di layar.")


async def _item_sku(ctx, sku: str, toko_id: Optional[str], terlihat: Optional[Dict[str, dict]]) -> List[dict]:
    """Item katalog ber-SKU persis `sku` (di semua toko yang terlihat, atau satu toko)."""
    d = await ctx.api("GET", P_CARI_ITEM, params={"q": sku.strip(), "account_id": toko_id, "limit": 100}) or {}
    s = sku.strip().upper()
    rows = [r for r in d.get("items") or []
            if s in (str(r.get("sku") or "").strip().upper(), str(r.get("variant_sku") or "").strip().upper())]
    if terlihat is not None:
        rows = [r for r in rows if r.get("account_id") in terlihat]
    return rows


def _nama_toko(terlihat: Dict[str, dict], r: dict) -> str:
    return (terlihat.get(r.get("account_id")) or {}).get("toko") or r.get("account_name") or "toko"


async def _sasaran_harga(ctx, args: dict) -> Tuple[List[dict], Dict[str, dict]]:
    terlihat = await TP._toko_cv(ctx)
    TP._tolak_toko_luar(ctx, [e["toko_id"] for e in args["item"] if e.get("toko_id")], terlihat)
    out, tidak_ada, dipakai = [], [], {}
    for i, e in enumerate(args["item"]):
        rows = await _item_sku(ctx, e["sku"], e.get("toko_id"), terlihat)
        if not rows:
            tidak_ada.append(e["sku"] + (f" (toko {terlihat[e['toko_id']].get('toko')})" if e.get("toko_id") else ""))
            continue
        for r in rows:
            if r["id"] in dipakai:
                raise AlatError(400, f"SKU {e['sku']} di {_nama_toko(terlihat, r)} disebut dua kali; satukan dulu "
                                     "harganya.")
            dipakai[r["id"]] = i
            out.append({"i": i, "e": e, "r": r, "toko": _nama_toko(terlihat, r)})
    if tidak_ada:
        raise AlatError(404, "SKU berikut tidak ada di katalog toko yang bisa Anda ubah pada CV "
                             f"{TP.CV_LABEL.get(ctx.cv, ctx.cv)}: {', '.join(tidak_ada[:8])}. Periksa SKU-nya di layar "
                             "Katalog.")
    return out, terlihat


def _nilai_baru(s: dict) -> Tuple[float, float, float, float, List[str]]:
    """(lama_jual, lama_coret, baru_jual, baru_coret, kolom_berubah)."""
    r, e = s["r"], s["e"]
    lj, lc = float(r.get("harga_jual") or 0), float(r.get("harga_coret") or 0)
    bj = float(e["harga_jual"])
    bc = float(e["harga_coret"]) if e.get("harga_coret") is not None else lc
    kolom = [k for k, a, b in (("harga_jual", lj, bj), ("harga_coret", lc, bc)) if round(a, 2) != round(b, 2)]
    return lj, lc, bj, bc, kolom


def _teks_harga(jual: float, coret: float, hpp: float) -> str:
    from core import margin as M
    t = rp(jual) + (f" · coret {rp(coret)}" if coret else "")
    if hpp > 0 and jual > 0:
        t += f" · margin {_pct(M.margin_of(jual, hpp, nd=1)['margin_pct'])}"
    return t


async def _rencana_harga(ctx, args: dict) -> Tuple[dict, List[dict]]:
    TP._cek_cv_tulis(ctx)
    _alasan(args)
    _cek_penulis_katalog(ctx)
    for e in args["item"]:
        if float(e.get("harga_jual") or 0) <= 0:
            raise AlatError(400, f"Harga jual {e['sku']} harus lebih dari Rp 0.")
        if e.get("harga_coret") not in (None, 0) and float(e["harga_coret"]) < float(e["harga_jual"]):
            raise AlatError(400, f"Harga coret {e['sku']} ({rp(e['harga_coret'])}) harus sama dengan atau lebih besar "
                                 f"dari harga jualnya ({rp(e['harga_jual'])}); isi 0 untuk tanpa harga coret.")
    sasaran, _terlihat = await _sasaran_harga(ctx, args)
    perubahan, peringatan, catatan_hpp, resmi, ubah = [], [], [], [], []
    berubah, sama, naik, turun = [], 0, 0, 0
    for s in sasaran:
        r = s["r"]
        lj, lc, bj, bc, kolom = _nilai_baru(s)
        if not kolom:
            sama += 1
            continue
        berubah.append({**s, "lama": (lj, lc), "baru": (bj, bc), "kolom": kolom})
        naik += int(bj > lj)
        turun += int(bj < lj)
        hpp = float(r.get("hpp_effective") or 0)
        nama = f"{r.get('sku')} · {s['toko']}"
        perubahan.append({"label": nama, "sebelum": _teks_harga(lj, lc, hpp), "sesudah": _teks_harga(bj, bc, hpp)})
        if hpp <= 0:
            catatan_hpp.append(f"{nama}: margin belum bisa diukur (HPP belum diketahui).")
        else:
            if bj < hpp:
                peringatan.append(f"Harga baru {nama} {rp(bj)} DI BAWAH HPP {rp(hpp)}: rugi {rp(hpp - bj)} per pcs.")
            if r.get("hpp_is_estimate"):
                catatan_hpp.append(f"{nama}: HPP {rp(hpp)} masih {r.get('hpp_source_label') or 'estimasi'}.")
        if lj and (bj > lj * 1.5 or bj < lj * 0.7):
            peringatan.append(f"Harga {nama} berubah {(bj / lj - 1) * 100:+.0f}% dari harga lama.")
        if bc and bc < bj:
            peringatan.append(f"Harga coret {nama} ({rp(bc)}) lebih kecil dari harga jual baru; sebutkan harga coret "
                              "baru bila perlu.")
        if r.get("is_active") is False:
            peringatan.append(f"Item {nama} sudah dihentikan (non-aktif) di katalog.")
        off = float(r.get("retail_price_master") or 0)
        if off and round(off) != round(bj):
            resmi.append(f"{nama} (harga resmi {rp(off)})")
    if not berubah:
        raise AlatError(409, "Harga semua item itu sudah sama persis dengan isian ini; tidak ada yang perlu diubah.")
    for i, e in enumerate(args["item"]):
        if not any(b["i"] == i for b in berubah):
            continue
        di = f" di {next(b['toko'] for b in berubah if b['i'] == i)}" if e.get("toko_id") else ""
        ubah.append({"kunci": f"item.{i}.harga_jual", "label": f"Harga jual {e['sku']}{di}", "jenis": "rupiah",
                     "nilai": e["harga_jual"]})
        if e.get("harga_coret") is not None:
            ubah.append({"kunci": f"item.{i}.harga_coret", "label": f"Harga coret {e['sku']}{di}", "jenis": "rupiah",
                         "nilai": e["harga_coret"]})
    ubah.insert(0, _ubah_alasan(args))
    catatan = ["Harga di Seller Center / TikTok Shop TIDAK ikut berubah; ubah juga di sana. Harga ini dipakai sebagai "
               "harga bawaan pesanan manual dan hitungan margin di DAHOST.",
               "Setiap perubahan tercatat di riwayat harga (Jejak Perubahan Marketing) beserta alasan dan tanda "
               "'Asisten AI'."]
    if sama:
        catatan.append(f"{sama} item lain sudah berharga sama dan dilewati.")
    if resmi:
        catatan.append("Berbeda dengan harga resmi Master Produk: " + "; ".join(resmi[:6])
                       + ("…" if len(resmi) > 6 else "") + ".")
    catatan += catatan_hpp[:6]
    n_toko = len({b["r"].get("account_id") for b in berubah})
    rencana = TP._batasi({
        "judul": "Ubah harga jual katalog",
        "ringkas": f"{len(berubah)} item katalog di {n_toko} toko — {naik} naik, {turun} turun"
                   + (f", {len(berubah) - naik - turun} hanya harga coret." if len(berubah) - naik - turun else "."),
        "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
        "tautan": {"label": "Buka layar Katalog", "menu": "marketing-catalog"}})
    return rencana, berubah


async def _tulis_harga(ctx, entri: List[dict], kunci: str, alasan: str) -> List[str]:
    """Tulis harga `kunci` ('sebelum'|'sesudah') per entri pembatalan, urutan terbalik. Return kegagalan."""
    gagal = []
    for e in reversed(entri):
        body = {k: e[kunci][k] for k in e["kolom"]}
        body["reason"] = alasan
        try:
            await TP._tulis(ctx, "PUT", f"/api/marketing/catalogs/{e['catalog_id']}/items/{e['item_id']}", json=body)
        except AlatError as x:
            gagal.append(f"{e['sku']} {e['toko']}: {x.pesan}")
    return gagal


@tindakan(
    name="ubah_harga_jual",
    label="Mengubah harga jual katalog",
    description=(
        "MENYIAPKAN perubahan harga jual (dan bila disebut harga coret) satu atau banyak SKU di katalog toko online — "
        "sama dengan mengubah item di layar Katalog Marketing. Kartu menampilkan harga lama → baru per SKU per toko "
        "dan margin terhadap HPP bila HPP diketahui (peringatan bila di bawah HPP).\n"
        "toko_id kosong = SKU itu di SEMUA toko yang Anda pegang pada CV terpilih. Aturan: hanya tim Marketing "
        "pengelola toko (atau izin kelola toko / setujui harga); harga coret harus ≥ harga jual (0 = tanpa harga "
        "coret). Harga di Seller Center tidak ikut berubah. Setiap perubahan masuk riwayat harga (lihat "
        "riwayat_harga). Bisa dibalikkan: harga lama dipulihkan bila belum diubah orang lain."),
    input_schema={
        "type": "object",
        "properties": {
            "item": {"type": "array", "minItems": 1, "maxItems": 30, "description": "Harga baru per SKU.",
                     "items": {"type": "object", "properties": {
                         "sku": {"type": "string", "minLength": 2, "maxLength": 80, "description": "SKU item katalog."},
                         "toko_id": {"type": "string", "minLength": 1,
                                     "description": "Id toko (opsional; kosong = semua toko yang memuat SKU ini)."},
                         "harga_jual": {"type": "number", "minimum": 1, "maximum": 1e9,
                                        "description": "Harga jual baru (Rp)."},
                         "harga_coret": {"type": "number", "minimum": 0, "maximum": 1e9,
                                         "description": "Harga coret baru (Rp, opsional; kosong = tetap)."}},
                         "required": ["sku", "harga_jual"], "additionalProperties": False}},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["item", "alasan"],
        "additionalProperties": False,
    },
    domain="penjualan",
    risiko="menengah",
    menu="marketing-catalog",
)
class UbahHargaJual:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_harga(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, berubah = await _rencana_harga(ctx, args)
        alasan = TP._jejak(_alasan(args))
        selesai: List[dict] = []
        try:
            for b in berubah:
                r = b["r"]
                e = {"catalog_id": r["catalog_id"], "item_id": r["id"], "sku": r.get("sku"), "toko": b["toko"],
                     "toko_id": r.get("account_id"), "kolom": b["kolom"],
                     "sebelum": {"harga_jual": b["lama"][0], "harga_coret": b["lama"][1]},
                     "sesudah": {"harga_jual": b["baru"][0], "harga_coret": b["baru"][1]}}
                body = {k: e["sesudah"][k] for k in e["kolom"]}
                body["reason"] = alasan
                await TP._tulis(ctx, "PUT", f"/api/marketing/catalogs/{e['catalog_id']}/items/{e['item_id']}", json=body)
                selesai.append(e)
        except AlatError as x:
            gagal = await _tulis_harga(ctx, selesai, "sebelum", TP._jejak("dibatalkan otomatis: tindakan gagal"))
            raise TP._gagal_sebagian("Perubahan harga", x, gagal) from None
        naik = sum(1 for e in selesai if e["sesudah"]["harga_jual"] > e["sebelum"]["harga_jual"])
        turun = sum(1 for e in selesai if e["sesudah"]["harga_jual"] < e["sebelum"]["harga_jual"])
        return {"ringkas": f"Harga {len(selesai)} item katalog diubah ({naik} naik, {turun} turun).",
                "hasil": {"item": [{"sku": e["sku"], "toko": e["toko"], "item_id": e["item_id"]} for e in selesai]},
                "sebelum": [{"label": f"{e['sku']} · {e['toko']}",
                             "nilai": _teks_harga(e["sebelum"]["harga_jual"], e["sebelum"]["harga_coret"], 0)}
                            for e in selesai],
                "sesudah": [{"label": f"{e['sku']} · {e['toko']}",
                             "nilai": _teks_harga(e["sesudah"]["harga_jual"], e["sesudah"]["harga_coret"], 0)}
                            for e in selesai],
                "pembatalan": {"item": selesai}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("item") or [])
        beda = []
        for e in entri:
            kini = [r for r in await _item_sku(ctx, e["sku"], e.get("toko_id"), None) if r.get("id") == e["item_id"]]
            if not kini:
                beda.append(f"{e['sku']} {e['toko']} (item sudah tidak ada)")
                continue
            for k in e["kolom"]:
                if round(float(kini[0].get(k) or 0), 2) != round(float(e["sesudah"][k] or 0), 2):
                    beda.append(f"{e['sku']} {e['toko']} (sekarang {rp(kini[0].get(k))})")
                    break
        if beda:
            raise AlatError(409, "Harga item berikut sudah diubah lagi sesudah tindakan ini: " + ", ".join(beda[:8])
                            + ". Pembalikan dibatalkan supaya perubahan itu tidak tertimpa; ubah manual di layar "
                              "Katalog bila perlu.")
        gagal = await _tulis_harga(ctx, entri, "sebelum", TP._jejak("membalikkan tindakan"))
        if gagal:
            raise _gagal_balik("harga", gagal)
        return {"ringkas": f"Harga {len(entri)} item katalog dikembalikan seperti sebelum tindakan."}


# ── riwayat harga (BACA) ──────────────────────────────────────────────────────
def _waktu_wib(iso: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(iso or "")[:16]
    if dt.tzinfo is not None:
        dt = dt.astimezone(TP.WIB)
    return f"{TP.label_tanggal(dt.date().isoformat())} {dt.strftime('%H.%M')} WIB"


async def _peta_item_toko(ctx, akun_ids: List[str]) -> Dict[str, dict]:
    """id item katalog → {sku, nama} untuk toko-toko ini (lewat daftar katalog + daftar item layar Katalog)."""
    peta: Dict[str, dict] = {}
    for aid in akun_ids[:8]:
        kat = await ctx.api("GET", "/api/marketing/catalogs", params={"account_id": aid}) or {}
        for c in (kat.get("catalogs") or [])[:3]:
            d = await ctx.api("GET", f"/api/marketing/catalogs/{c['id']}/items", params={"limit": 5000}) or {}
            for it in d.get("items") or []:
                peta[it["id"]] = {"sku": it.get("sku"), "nama": it.get("name")}
    return peta


@alat(
    name="riwayat_harga",
    kind="read",
    label="Membaca riwayat harga jual",
    description=(
        "Riwayat perubahan harga jual dan harga coret item katalog toko (dari Jejak Perubahan Marketing): waktu (WIB), "
        "toko, SKU, nama produk, harga lama → baru, siapa (nama & peran), alasan, dan apakah lewat Asisten AI; urut "
        "terbaru. Bila SKU disebut juga memberi harga SEKARANG per toko beserta margin terhadap HPP. Perubahan "
        "sebelum fitur riwayat harga dipasang tidak tercatat. Pakai sebelum menyarankan atau mengubah harga."),
    input_schema={"type": "object", "properties": {
        "sku": {"type": "string", "minLength": 2, "maxLength": 80, "description": "SKU (opsional)."},
        "toko_id": {"type": "string", "minLength": 1, "description": "Id toko (opsional)."},
        "dari": {**TANGGAL, "description": "Tanggal awal perubahan (TTTT-BB-HH, opsional)."},
        "sampai": {**TANGGAL, "description": "Tanggal akhir perubahan (TTTT-BB-HH, opsional)."},
        "batas": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Jumlah baris (bawaan 20)."},
    }, "additionalProperties": False},
    domain="penjualan",
)
async def riwayat_harga(ctx, args: dict) -> dict:
    args = args or {}
    batas = int(args.get("batas") or 20)
    terlihat = None if str(ctx.cv).upper() == "ALL" else await TP._toko_cv(ctx)
    if args.get("toko_id") and terlihat is not None:
        TP._tolak_toko_luar(ctx, [args["toko_id"]], terlihat)
    data = await ctx.api("GET", P_LOG, params=B.params(
        entity="catalog_item", action="price_change", account_id=args.get("toko_id"),
        date_from=args.get("dari"), date_to=args.get("sampai"), page_size=500)) or {}
    rows = list(data.get("rows") or [])
    if terlihat is not None:
        rows = [r for r in rows if r.get("account_id") in terlihat]
    harga_kini, peta = [], {}
    if args.get("sku"):
        items = await _item_sku(ctx, args["sku"], args.get("toko_id"), terlihat)
        peta = {r["id"]: {"sku": r.get("sku"), "nama": r.get("name")} for r in items}
        rows = [r for r in rows if r.get("entity_id") in peta]
        for r in items:
            hpp = float(r.get("hpp_effective") or 0)
            harga_kini.append({"toko": r.get("account_name") or (terlihat or {}).get(r.get("account_id"), {}).get("toko"),
                               "harga_jual": rp(r.get("harga_jual")),
                               "harga_coret": rp(r.get("harga_coret")) if r.get("harga_coret") else "—",
                               "hpp": rp(hpp) if hpp > 0 else "belum diketahui",
                               "margin": _pct(r["margin_pct"]) if r.get("margin_pct") is not None else "belum bisa diukur"})
    total = len(rows)
    rows = rows[:batas]
    if not args.get("sku") and rows:
        peta = await _peta_item_toko(ctx, list(dict.fromkeys(r["account_id"] for r in rows if r.get("account_id"))))
    daftar = []
    for r in rows:
        it = peta.get(r.get("entity_id")) or {}
        ch = {c.get("field"): c for c in r.get("changes") or []}
        baris = {"waktu": _waktu_wib(r.get("at")), "toko": r.get("account_name"),
                 "sku": it.get("sku") or "(item sudah dihapus)", "produk": it.get("nama"),
                 "oleh": r.get("actor_name"), "peran": r.get("actor_role"), "alasan": r.get("reason") or "—",
                 "lewat_asisten_ai": str(r.get("reason") or "").startswith("Asisten AI")}
        for k, lbl in (("harga_jual", "harga_jual"), ("harga_coret", "harga_coret")):
            if k in ch:
                baris[lbl] = f"{rp(ch[k].get('before'))} → {rp(ch[k].get('after'))}"
        daftar.append({k: v for k, v in baris.items() if v is not None})
    hasil = {"jumlah_perubahan": total, "ditampilkan": len(daftar), "riwayat": daftar,
             "catatan": "Riwayat harga baru tercatat sejak fitur riwayat harga dipasang; perubahan sebelum itu tidak "
                        "ada di sini. Harga di Seller Center tidak tercatat di DAHOST.",
             "_sumber": "Riwayat harga (Jejak Perubahan Marketing)"}
    if args.get("sku"):
        hasil["harga_sekarang"] = harga_kini
    if total > len(daftar):
        hasil["catatan_daftar"] = f"Menampilkan {len(daftar)} perubahan terbaru dari {total}."
    return B.padatkan(hasil)


# ══════════════════════════════════════════════════════════════════════════════
# 2. PROMO / KAMPANYE DISKON
# ══════════════════════════════════════════════════════════════════════════════
P_DISKON = "/api/marketing/discounts"
JENIS_DISKON = ("flash_sale", "voucher", "bundling", "buy_x_get_y", "free_shipping", "diskon_persen", "cashback",
                "giveaway")             # = routes.marketing_discounts_routes.DISCOUNT_TYPES
LABEL_JENIS = {"flash_sale": "Flash sale", "voucher": "Voucher / kupon", "bundling": "Bundling produk",
               "buy_x_get_y": "Beli X gratis Y", "free_shipping": "Gratis ongkir", "diskon_persen": "Diskon %",
               "cashback": "Cashback", "giveaway": "Giveaway"}
LABEL_STATUS = {"active": "Aktif", "upcoming": "Akan datang", "expired": "Berakhir", "draft": "Tanggal tidak sah"}
# isian alat → kolom endpoint diskon
KOLOM_PROMO = {"nama": "name", "jenis": "discount_type", "nilai": "discount_value", "satuan": "discount_unit",
               "min_pembelian": "min_purchase", "maks_diskon": "max_discount", "mulai": "start_date",
               "berakhir": "end_date", "keterangan": "description", "cakupan_produk": "product_scope"}
LABEL_KOLOM = {"name": "Nama", "discount_type": "Jenis", "discount_value": "Nilai", "discount_unit": "Satuan",
               "min_purchase": "Min. pembelian", "max_discount": "Maks. diskon", "start_date": "Mulai",
               "end_date": "Berakhir", "description": "Keterangan", "product_scope": "Cakupan produk"}


def _cek_penulis_diskon(ctx) -> None:
    from routes.marketing_discounts_routes import DISCOUNT_WRITER_ROLES
    from routes.shared import can_act
    if not can_act(ctx.user, "toko.manage", legacy_roles=DISCOUNT_WRITER_ROLES):
        raise AlatError(403, "Akun Anda tidak boleh membuat atau mengubah kampanye diskon: itu wewenang tim Marketing "
                             "pengelola toko (PIC/staf toko, SPV/Manager Marketing) atau owner.")


def _teks_nilai(v: Any, satuan: Optional[str]) -> str:
    if satuan == "nominal":
        return rp(v)
    if satuan == "unit":
        return f"{_q(v)} unit"
    return f"{_q(v)}%"


def _teks_kolom(k: str, v: Any, promo: dict) -> str:
    if v in (None, ""):
        return "—"
    if k == "discount_type":
        return LABEL_JENIS.get(v, v)
    if k == "discount_value":
        return _teks_nilai(v, promo.get("discount_unit"))
    if k == "discount_unit":
        return {"persen": "persen", "nominal": "Rupiah", "unit": "unit"}.get(v, v)
    if k in ("min_purchase", "max_discount"):
        return rp(v) if float(v or 0) else "—"
    if k in ("start_date", "end_date"):
        return _tgl(v)
    if k == "product_scope":
        return "semua produk" if v == "semua_produk" else str(v)
    return str(v)[:120]


def _status_promo(ctx, p: dict) -> str:
    hari = B.hari_ini(ctx).isoformat()
    s, e = str(p.get("start_date") or "")[:10], str(p.get("end_date") or "")[:10]
    if not s or not e:
        return "draft"
    return "upcoming" if hari < s else ("expired" if hari > e else "active")


async def _daftar_diskon(ctx, toko_id: Optional[str] = None, *, cari: Optional[str] = None,
                         status: Optional[str] = None, maks_halaman: int = 20) -> List[dict]:
    out = []
    for hal in range(1, maks_halaman + 1):
        d = await ctx.api("GET", P_DISKON, params=B.params(page=hal, page_size=100, account_id=toko_id,
                                                           search=cari, status=status)) or {}
        out += d.get("data") or []
        if hal >= int((d.get("pagination") or {}).get("total_pages") or 1):
            break
    return out


async def _cari_promo(ctx, args: dict, terlihat: Dict[str, dict]) -> dict:
    if args.get("promo_id"):
        semua = await _daftar_diskon(ctx, args.get("toko_id"))
        cocok = [p for p in semua if p.get("id") == args["promo_id"]]
    elif args.get("nama_promo"):
        nama = args["nama_promo"].strip().lower()
        semua = [p for p in await _daftar_diskon(ctx, args.get("toko_id"), cari=re.escape(args["nama_promo"].strip()))
                 if not p.get("_seed_origin")]
        cocok = [p for p in semua if str(p.get("name") or "").strip().lower() == nama] or semua
    else:
        raise AlatError(400, "Sebutkan promo yang dimaksud (promo_id dari daftar_promo, atau nama_promo).")
    cocok = [p for p in cocok if p.get("account_id") in terlihat] if terlihat is not None else cocok
    if not cocok:
        raise AlatError(404, "Promo itu tidak ditemukan di toko yang Anda pegang pada CV ini. Lihat daftar_promo.")
    if len(cocok) > 1:
        raise AlatError(400, "Ada beberapa promo yang cocok: " + "; ".join(
            f"{p.get('name')} ({_nama_toko(terlihat, p)}, {_tgl(p.get('start_date'))}–{_tgl(p.get('end_date'))}, "
            f"id {p.get('id')})" for p in cocok[:5]) + ". Sebutkan promo_id-nya.")
    return cocok[0]


def _cek_nilai_promo(nilai: Any, satuan: Optional[str]) -> None:
    if (satuan or "persen") == "persen" and float(nilai or 0) > 100:
        raise AlatError(400, f"Diskon persen tidak boleh lebih dari 100% (isian {_q(nilai)}%).")


async def _rencana_promo(ctx, args: dict) -> Tuple[dict, dict]:
    """(rencana kartu, rencana tulis {aksi, promo?, body})."""
    TP._cek_cv_tulis(ctx)
    _alasan(args)
    _cek_penulis_diskon(ctx)
    aksi = args["aksi"]
    terlihat = await TP._toko_cv(ctx)
    perubahan, peringatan, catatan, ubah = [], [], [], []
    hari = B.hari_ini(ctx)
    if aksi == "buat":
        kurang = [k for k in ("toko_id", "nama", "jenis", "mulai", "berakhir") if not args.get(k)]
        if kurang:
            raise AlatError(400, "Untuk membuat promo sebutkan: " + ", ".join(kurang) + ".")
        TP._tolak_toko_luar(ctx, [args["toko_id"]], terlihat)
        mulai = TP._cek_tanggal_depan(ctx, args["mulai"], "Tanggal mulai promo")
        akhir = TP._tanggal_sah(args["berakhir"], "Tanggal berakhir promo")
        if akhir < mulai:
            raise AlatError(400, "Tanggal berakhir promo tidak boleh sebelum tanggal mulainya.")
        if (akhir - mulai).days > 366:
            raise AlatError(400, "Promo paling lama satu tahun.")
        satuan = args.get("satuan") or "persen"
        _cek_nilai_promo(args.get("nilai"), satuan)
        akun = await TP._akun(ctx, args["toko_id"], {})
        toko = terlihat[args["toko_id"]].get("toko") or akun.get("account_name") or args["toko_id"]
        body = {"account_id": args["toko_id"], "account_name": akun.get("account_name") or toko,
                "platform": akun.get("platform") or "shopee", "name": args["nama"].strip(),
                "discount_type": args["jenis"], "discount_value": float(args.get("nilai") or 0),
                "discount_unit": satuan, "min_purchase": float(args.get("min_pembelian") or 0),
                "max_discount": float(args.get("maks_diskon") or 0), "start_date": args["mulai"],
                "end_date": args["berakhir"], "description": args.get("keterangan") or "",
                "product_scope": args.get("cakupan_produk") or "semua_produk"}
        perubahan.append({"label": "Toko", "sebelum": "—", "sesudah": toko})
        for k in ("name", "discount_type", "discount_value", "min_purchase", "max_discount", "product_scope"):
            if k in ("min_purchase", "max_discount") and not body[k]:
                continue
            perubahan.append({"label": LABEL_KOLOM[k], "sebelum": "—", "sesudah": _teks_kolom(k, body[k], body)})
        perubahan.append({"label": "Periode", "sebelum": "—",
                          "sesudah": f"{_tgl(body['start_date'])} – {_tgl(body['end_date'])}"})
        if not body["discount_value"] and args["jenis"] not in ("free_shipping", "giveaway", "buy_x_get_y"):
            peringatan.append("Nilai diskon Rp 0 / 0% — periksa lagi nilainya.")
        lain = [p for p in await _daftar_diskon(ctx, args["toko_id"]) if not p.get("_seed_origin")
                and p.get("discount_type") == args["jenis"] and str(p.get("start_date"))[:10] <= args["berakhir"]
                and str(p.get("end_date"))[:10] >= args["mulai"]]
        if lain:
            peringatan.append("Sudah ada promo sejenis yang tanggalnya bertumpuk di toko ini: " + "; ".join(
                f"{p.get('name')} ({_tgl(p.get('start_date'))}–{_tgl(p.get('end_date'))})" for p in lain[:4]) + ".")
        ubah += [{"kunci": "nilai", "label": "Nilai diskon", "jenis": "rupiah" if satuan == "nominal" else "angka",
                  "nilai": body["discount_value"]} if "nilai" in args else None,
                 {"kunci": "mulai", "label": "Tanggal mulai", "jenis": "tanggal", "nilai": args["mulai"]},
                 {"kunci": "berakhir", "label": "Tanggal berakhir", "jenis": "tanggal", "nilai": args["berakhir"]},
                 {"kunci": "nama", "label": "Nama promo", "jenis": "teks", "nilai": args["nama"]}]
        judul, ringkas = f"Buat promo di {toko}", (f"{LABEL_JENIS.get(args['jenis'])} "
                                                   f"{_teks_nilai(body['discount_value'], satuan)}, "
                                                   f"{_tgl(args['mulai'])} – {_tgl(args['berakhir'])}.")
        tulis = {"aksi": "buat", "body": body, "toko": toko}
    else:
        p = await _cari_promo(ctx, args, terlihat)
        toko = _nama_toko(terlihat, p)
        st = _status_promo(ctx, p)
        if p.get("_seed_origin"):
            peringatan.append("Promo ini data contoh (bukan promo sungguhan).")
        if aksi == "akhiri":
            if st == "upcoming":
                raise AlatError(409, f"Promo '{p.get('name')}' belum mulai (mulai {_tgl(p.get('start_date'))}). Untuk "
                                     "membatalkannya, ubah tanggalnya atau hapus di layar Diskon (hapus hanya untuk "
                                     "owner/manager/PIC toko).")
            if st == "expired" or str(p.get("end_date"))[:10] == hari.isoformat():
                raise AlatError(409, f"Promo '{p.get('name')}' sudah berakhir ({_tgl(p.get('end_date'))}).")
            patch = {"end_date": hari.isoformat()}
            catatan.append("Diakhiri = tanggal berakhir menjadi hari ini; status di layar Diskon menjadi 'Berakhir' "
                           "mulai besok. Hentikan juga promonya di Seller Center / TikTok Shop.")
            judul = f"Akhiri promo {p.get('name')}"
        else:
            if st == "expired":
                raise AlatError(409, f"Promo '{p.get('name')}' sudah berakhir ({_tgl(p.get('end_date'))}); riwayat promo "
                                     "tidak diubah lewat Asisten AI.")
            patch = {}
            for a, k in KOLOM_PROMO.items():
                if args.get(a) is not None and a != "nama" or (a == "nama" and args.get("nama")):
                    v = args[a]
                    if k in ("discount_value", "min_purchase", "max_discount"):
                        v = float(v)
                    if str(p.get(k) if p.get(k) is not None else "") != str(v) and \
                            not (isinstance(v, float) and float(p.get(k) or 0) == v):
                        patch[k] = v
            if not patch:
                raise AlatError(409 if any(args.get(a) is not None for a in KOLOM_PROMO) else 400,
                                "Tidak ada isian promo yang berubah." if any(args.get(a) is not None for a in KOLOM_PROMO)
                                else "Sebutkan apa yang diubah dari promo itu (nilai, tanggal, nama, dll.).")
            mulai = patch.get("start_date", str(p.get("start_date"))[:10])
            akhir = patch.get("end_date", str(p.get("end_date"))[:10])
            if "start_date" in patch:
                _tanggal_maju(ctx, patch["start_date"], "Tanggal mulai promo", hari_maks=366)
            if "end_date" in patch:
                _tanggal_maju(ctx, patch["end_date"], "Tanggal berakhir promo", hari_maks=732)
            if akhir < mulai:
                raise AlatError(400, "Tanggal berakhir promo tidak boleh sebelum tanggal mulainya.")
            _cek_nilai_promo(patch.get("discount_value", p.get("discount_value")),
                             patch.get("discount_unit", p.get("discount_unit")))
            judul = f"Ubah promo {p.get('name')}"
            for a, k in KOLOM_PROMO.items():
                if k in patch:
                    jenis = "tanggal" if k in ("start_date", "end_date") else (
                        "rupiah" if k in ("min_purchase", "max_discount") or (
                            k == "discount_value" and patch.get("discount_unit", p.get("discount_unit")) == "nominal")
                        else "angka" if k == "discount_value" else None)
                    if jenis:
                        ubah.append({"kunci": a, "label": LABEL_KOLOM[k], "jenis": jenis, "nilai": args[a]})
        baru = {**p, **patch}
        for k, v in patch.items():
            perubahan.append({"label": LABEL_KOLOM[k], "sebelum": _teks_kolom(k, p.get(k), p),
                              "sesudah": _teks_kolom(k, v, baru)})
        ringkas = (f"{toko} · {LABEL_JENIS.get(p.get('discount_type'), p.get('discount_type'))} "
                   f"{_teks_nilai(baru.get('discount_value'), baru.get('discount_unit'))} · status sekarang "
                   f"{LABEL_STATUS.get(st, st).lower()}.")
        tulis = {"aksi": aksi, "promo": p, "patch": patch, "toko": toko}
    catatan.append("Ini catatan kampanye di DAHOST (layar Diskon); promo di Seller Center / TikTok Shop tetap diatur "
                   "di sana.")
    ubah = [_ubah_alasan(args)] + [u for u in ubah if u]
    return TP._batasi({"judul": judul, "ringkas": ringkas, "perubahan": perubahan, "catatan": catatan,
                       "peringatan": peringatan, "ubah": ubah,
                       "tautan": {"label": "Buka layar Diskon", "menu": "marketing-discounts"}}), tulis


async def _promo_kini(ctx, promo_id: str, toko_id: Optional[str]) -> Optional[dict]:
    return next((p for p in await _daftar_diskon(ctx, toko_id) if p.get("id") == promo_id), None)


def _sama(a: Any, b: Any) -> bool:
    try:
        return round(float(a), 4) == round(float(b), 4)
    except (TypeError, ValueError):
        return str(a if a is not None else "") == str(b if b is not None else "")


@tindakan(
    name="atur_promo",
    label="Mengatur promo toko",
    description=(
        "MENYIAPKAN pembuatan, perubahan, atau pengakhiran kampanye diskon/promo toko online — sama dengan layar "
        "Diskon Marketing. aksi 'buat' (wajib toko_id, nama, jenis, mulai, berakhir; nilai + satuan persen|nominal|"
        "unit), 'ubah' (promo_id atau nama_promo + isian yang diubah), 'akhiri' (tanggal berakhir menjadi hari ini; "
        "hanya promo yang sedang aktif).\n"
        "Jenis: flash_sale, voucher, bundling, buy_x_get_y, free_shipping, diskon_persen, cashback, giveaway. Aturan: "
        "tim Marketing pengelola toko atau owner; hanya toko yang Anda pegang pada CV terpilih; promo baru mulai hari "
        "ini atau sesudahnya; diskon persen ≤ 100; promo yang sudah berakhir tidak diubah. Promo di Seller Center tidak "
        "ikut berubah. Bisa dibalikkan: promo baru dihapus (atau diakhiri bila Anda tidak boleh menghapus), ubahan "
        "dikembalikan. Pakai daftar_promo untuk melihat promo yang ada."),
    input_schema={
        "type": "object",
        "properties": {
            "aksi": {"type": "string", "enum": ["buat", "ubah", "akhiri"]},
            "promo_id": {"type": "string", "minLength": 1, "description": "Id promo (untuk ubah/akhiri)."},
            "nama_promo": {"type": "string", "minLength": 2, "maxLength": 200,
                           "description": "Nama promo yang dicari (untuk ubah/akhiri bila id tidak diketahui)."},
            "toko_id": {"type": "string", "minLength": 1, "description": "Id toko (wajib untuk buat)."},
            "nama": {"type": "string", "minLength": 3, "maxLength": 200, "description": "Nama promo (baru)."},
            "jenis": {"type": "string", "enum": list(JENIS_DISKON)},
            "nilai": {"type": "number", "minimum": 0, "maximum": 1e9, "description": "Nilai diskon."},
            "satuan": {"type": "string", "enum": ["persen", "nominal", "unit"], "description": "Bawaan persen."},
            "min_pembelian": {"type": "number", "minimum": 0, "maximum": 1e10, "description": "Rp."},
            "maks_diskon": {"type": "number", "minimum": 0, "maximum": 1e10, "description": "Rp (0 = tanpa batas)."},
            "mulai": {**TANGGAL, "description": "Tanggal mulai (TTTT-BB-HH)."},
            "berakhir": {**TANGGAL, "description": "Tanggal berakhir (TTTT-BB-HH)."},
            "keterangan": {"type": "string", "maxLength": 1000},
            "cakupan_produk": {"type": "string", "maxLength": 200,
                               "description": "Produk yang ikut (bawaan semua_produk)."},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["aksi", "alasan"],
        "additionalProperties": False,
    },
    domain="penjualan",
    risiko="menengah",
    menu="marketing-discounts",
)
class AturPromo:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_promo(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, t = await _rencana_promo(ctx, args)
        if t["aksi"] == "buat":
            res = await TP._tulis(ctx, "POST", P_DISKON, json=t["body"])
            d = (res or {}).get("data") or {}
            return {"ringkas": f"Promo '{t['body']['name']}' dibuat di {t['toko']} "
                               f"({_tgl(t['body']['start_date'])} – {_tgl(t['body']['end_date'])}).",
                    "hasil": {"promo_id": d.get("id"), "toko": t["toko"]},
                    "pembatalan": {"aksi": "buat", "promo_id": d.get("id"), "toko_id": t["body"]["account_id"],
                                   "nama": t["body"]["name"],
                                   "sesudah": {k: t["body"][k] for k in ("name", "discount_type", "discount_value",
                                                                         "discount_unit", "start_date", "end_date")}}}
        p, patch = t["promo"], t["patch"]
        await TP._tulis(ctx, "PUT", f"{P_DISKON}/{p['id']}", json=patch)
        kata = "diakhiri hari ini" if t["aksi"] == "akhiri" else "diubah"
        return {"ringkas": f"Promo '{p.get('name')}' di {t['toko']} {kata}.",
                "hasil": {"promo_id": p["id"], "toko": t["toko"]},
                "pembatalan": {"aksi": t["aksi"], "promo_id": p["id"], "toko_id": p.get("account_id"),
                               "nama": p.get("name"), "sesudah": patch,
                               "sebelum": {k: p.get(k) for k in patch}}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        pid, nama = pembatalan["promo_id"], pembatalan.get("nama") or "promo"
        kini = await _promo_kini(ctx, pid, pembatalan.get("toko_id"))
        if kini is None:
            if pembatalan["aksi"] == "buat":
                return {"ringkas": f"Promo '{nama}' sudah tidak ada (sudah dihapus); tidak ada yang perlu dibalikkan."}
            raise AlatError(409, f"Promo '{nama}' sudah dihapus, jadi ubahannya tidak bisa dikembalikan.")
        beda = [LABEL_KOLOM.get(k, k) for k, v in (pembatalan.get("sesudah") or {}).items() if not _sama(kini.get(k), v)]
        if beda:
            raise AlatError(409, f"Promo '{nama}' sudah diubah lagi sesudah tindakan ini ({', '.join(beda)}). Pembalikan "
                                 "dibatalkan supaya perubahan itu tidak tertimpa; ubah manual di layar Diskon.")
        if pembatalan["aksi"] != "buat":
            await TP._tulis(ctx, "PUT", f"{P_DISKON}/{pid}", json=pembatalan.get("sebelum") or {})
            return {"ringkas": f"Promo '{nama}' dikembalikan seperti sebelum tindakan."}
        try:
            await TP._tulis(ctx, "DELETE", f"{P_DISKON}/{pid}")
            return {"ringkas": f"Promo '{nama}' yang dibuat tindakan ini dihapus."}
        except AlatError as e:
            if e.status != 403:
                raise
        if _status_promo(ctx, kini) == "active":
            await TP._tulis(ctx, "PUT", f"{P_DISKON}/{pid}", json={"end_date": B.hari_ini(ctx).isoformat()})
            return {"ringkas": f"Promo '{nama}' diakhiri hari ini (akun Anda tidak boleh menghapus promo; hapus hanya "
                               "untuk owner/manager/PIC toko)."}
        raise AlatError(403, f"Promo '{nama}' belum mulai dan akun Anda tidak boleh menghapus promo (hanya owner/"
                             "manager/PIC toko). Minta mereka menekan Balikkan atau menghapusnya di layar Diskon.")


@alat(
    name="daftar_promo",
    kind="read",
    label="Membaca daftar promo",
    description=(
        "Daftar kampanye diskon/promo toko online (layar Diskon Marketing) untuk toko yang dipegang pengguna pada CV "
        "terpilih: id, nama, toko, jenis, nilai, min. pembelian, maks. diskon, mulai, berakhir, status (aktif / akan "
        "datang / berakhir), sisa hari. Data contoh tidak ikut. Bisa disaring toko, status, atau kata kunci nama. "
        "Pakai untuk memilih promo sebelum atur_promo."),
    input_schema={"type": "object", "properties": {
        "toko_id": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["aktif", "akan_datang", "berakhir"]},
        "cari": {"type": "string", "minLength": 2, "maxLength": 80, "description": "Kata kunci nama promo."},
        "batas": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Jumlah baris (bawaan 20)."},
    }, "additionalProperties": False},
    domain="penjualan",
)
async def daftar_promo(ctx, args: dict) -> dict:
    args = args or {}
    terlihat = None if str(ctx.cv).upper() == "ALL" else await TP._toko_cv(ctx)
    if args.get("toko_id") and terlihat is not None:
        TP._tolak_toko_luar(ctx, [args["toko_id"]], terlihat)
    st = {"aktif": "active", "akan_datang": "upcoming", "berakhir": "expired"}.get(args.get("status") or "")
    rows = await _daftar_diskon(ctx, args.get("toko_id"), cari=re.escape(args["cari"]) if args.get("cari") else None,
                                status=st)
    contoh = sum(1 for r in rows if r.get("_seed_origin"))
    rows = [r for r in rows if not r.get("_seed_origin") and (terlihat is None or r.get("account_id") in terlihat)]
    batas = int(args.get("batas") or 20)
    daftar = [{"id": r.get("id"), "nama": r.get("name"), "toko": r.get("account_name"),
               "jenis": LABEL_JENIS.get(r.get("discount_type"), r.get("discount_type")),
               "nilai": _teks_nilai(r.get("discount_value"), r.get("discount_unit")),
               "min_pembelian": rp(r.get("min_purchase")) if r.get("min_purchase") else "—",
               "maks_diskon": rp(r.get("max_discount")) if r.get("max_discount") else "—",
               "mulai": str(r.get("start_date") or "")[:10], "berakhir": str(r.get("end_date") or "")[:10],
               "status": LABEL_STATUS.get(r.get("status"), r.get("status")), "sisa_hari": r.get("days_remaining")}
              for r in rows[:batas]]
    hasil = {"jumlah": len(rows), "per_status": {LABEL_STATUS.get(s, s): sum(1 for r in rows if r.get("status") == s)
                                                 for s in ("active", "upcoming", "expired")},
             "promo": daftar, "_sumber": "Kampanye diskon (layar Diskon)"}
    if contoh:
        hasil["catatan"] = f"{contoh} promo data contoh tidak ditampilkan."
    if len(rows) > batas:
        hasil["catatan_daftar"] = f"Menampilkan {batas} dari {len(rows)} promo."
    return B.padatkan(hasil)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PO PRODUKSI — tenggat & draf
# ══════════════════════════════════════════════════════════════════════════════
P_PO = "/api/production-pos"
STATUS_PO = {"Draft": "Draf", "Confirmed": "Dikonfirmasi", "Distributed": "Didistribusikan",
             "In Production": "Sedang produksi", "Production Complete": "Produksi selesai",
             "Variance Review": "Tinjau selisih", "Return Review": "Tinjau retur", "Ready to Close": "Siap ditutup",
             "Closed": "Ditutup", "Completed": "Selesai", "Closed Short": "Ditutup kurang"}
JENIS_PO = {"internal": "PO produksi internal", "maklon": "PO maklon"}
MENU_PO = {"internal": "prod-pos-internal", "maklon": "maklon-pos-engine"}
KOLOM_TENGGAT = (("tenggat_produksi", "deadline", "Tenggat produksi"),
                 ("tenggat_kirim", "delivery_deadline", "Tenggat kirim"))


async def _cari_po(ctx, nomor: str) -> dict:
    n = nomor.strip()
    rows = await ctx.api("GET", P_PO, params={"search": re.escape(n)})
    rows = rows if isinstance(rows, list) else (rows or {}).get("items") or []
    cocok = [r for r in rows if str(r.get("po_number") or "").strip().upper() == n.upper()]
    if not cocok:
        raise AlatError(404, f"PO {n} tidak ditemukan. Periksa nomornya di layar PO Produksi.")
    return cocok[0]


async def _izin_po(ctx, bt: str, aksi: str) -> dict:
    izin = await ctx.api("GET", f"{P_PO}/permissions", params={"business_type": bt}) or {}
    if not izin.get(f"can_{aksi}"):
        kata = {"create": "membuat", "edit": "mengubah", "delete": "menghapus"}[aksi]
        raise AlatError(403, f"Akun Anda tidak boleh {kata} {JENIS_PO.get(bt, 'PO')} (aturan yang sama dengan tombol di "
                             "layar PO). Minta owner mencentang izinnya di Peran & Hak Akses bila memang perlu.")
    return izin


def _hari_beda(lama: Optional[str], baru: str) -> str:
    if not lama:
        return ""
    d = (date.fromisoformat(baru) - date.fromisoformat(lama[:10])).days
    return f" ({'+' if d > 0 else '−' if d < 0 else '±'}{abs(d)} hari)" if d else ""


async def _rencana_tenggat(ctx, args: dict) -> Tuple[dict, List[dict]]:
    from core.maklon_ledger import CLOSED_PO_STATUSES
    TP._cek_cv_tulis(ctx)
    _alasan(args)
    daftar = args["po"]
    nomor = [p["nomor_po"].strip().upper() for p in daftar]
    if len(set(nomor)) != len(nomor):
        raise AlatError(400, "Ada PO yang disebut dua kali; satukan dulu tanggalnya.")
    perubahan, peringatan, ubah, sasaran = [], [], [], []
    izin_cek = set()
    hari = B.hari_ini(ctx)
    for i, a in enumerate(daftar):
        if not a.get("tenggat_produksi") and not a.get("tenggat_kirim"):
            raise AlatError(400, f"Sebutkan tenggat produksi dan/atau tenggat kirim baru untuk PO {a['nomor_po']}.")
        po = await _cari_po(ctx, a["nomor_po"])
        bt = po.get("business_type") or "internal"
        st = po.get("status") or "Draft"
        label = f"{po['po_number']}"
        if st in CLOSED_PO_STATUSES:
            raise AlatError(409, f"PO {label} sudah ditutup ({STATUS_PO.get(st, st)}); PO yang ditutup terkunci.")
        if bt == "maklon" and st != "Draft":
            raise AlatError(409, f"PO maklon {label} sudah {STATUS_PO.get(st, st).lower()}: mengubahnya ikut menyegarkan "
                                 "jadwal piutang klien dan hutang CMT, jadi tidak lewat Asisten AI. Ubah tenggatnya di "
                                 "layar PO Maklon.")
        if bt not in izin_cek:
            await _izin_po(ctx, bt, "edit")
            izin_cek.add(bt)
        patch, lama = {}, {}
        for kunci, kolom, nama in KOLOM_TENGGAT:
            if not a.get(kunci):
                continue
            _tanggal_maju(ctx, a[kunci], f"{nama} PO {label}")
            l = str(po.get(kolom) or "")[:10] or None
            if l != a[kunci]:
                patch[kolom], lama[kolom] = a[kunci], l
                perubahan.append({"label": f"{label} · {nama}", "sebelum": _tgl(l),
                                  "sesudah": _tgl(a[kunci]) + _hari_beda(l, a[kunci])})
            ubah.append({"kunci": f"po.{i}.{kunci}", "label": f"{nama} {label}", "jenis": "tanggal", "nilai": a[kunci]})
        if not patch:
            continue
        akhir_prod = patch.get("deadline", str(po.get("deadline") or "")[:10])
        akhir_kirim = patch.get("delivery_deadline", str(po.get("delivery_deadline") or "")[:10])
        if akhir_prod and akhir_kirim and akhir_kirim < akhir_prod:
            peringatan.append(f"PO {label}: tenggat kirim ({_tgl(akhir_kirim)}) lebih awal dari tenggat produksi "
                              f"({_tgl(akhir_prod)}).")
        if lama.get("deadline") and lama["deadline"] < hari.isoformat():
            peringatan.append(f"PO {label} sudah lewat tenggat produksi sejak {_tgl(lama['deadline'])}.")
        tot, qc = int(po.get("total_qty") or 0), int(po.get("total_accepted_qc") or 0)
        sasaran.append({"po_id": po["id"], "nomor": label, "jenis": bt, "status": st, "patch": patch, "sebelum": lama,
                        "progres": f"{_q(qc)}/{_q(tot)} pcs lolos QC" if tot else ""})
    if not sasaran:
        raise AlatError(409, "Tenggat PO itu sudah sama persis dengan isian ini; tidak ada yang perlu diubah.")
    ubah.insert(0, _ubah_alasan(args))
    jenis = {s["jenis"] for s in sasaran}
    catatan = ["Hanya tanggal tenggat yang berubah; status, baris produk, penjahit, dan upah jahit PO tidak disentuh.",
               "Disimpan lewat jalur yang sama dengan tombol Ubah di layar PO (izin dan kunci PO berlaku)."]
    catatan += [f"PO {s['nomor']}: {STATUS_PO.get(s['status'], s['status'])}" + (f", {s['progres']}." if s["progres"]
                                                                                 else ".") for s in sasaran[:6]]
    if str(ctx.cv).upper() == "SMU" and "internal" in jenis:
        catatan.append("PO produksi internal milik CV DA; pilihan CV Sukma tidak mengubah PO-nya.")
    menu = MENU_PO["maklon" if jenis == {"maklon"} else "internal"]
    return TP._batasi({
        "judul": "Ubah tenggat PO produksi" if len(sasaran) > 1 else f"Ubah tenggat PO {sasaran[0]['nomor']}",
        "ringkas": f"{len(sasaran)} PO, {len(perubahan)} tanggal tenggat diubah.",
        "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
        "tautan": {"label": "Buka layar PO", "menu": menu}}), sasaran


@tindakan(
    name="ubah_tenggat_po_produksi",
    label="Mengubah tenggat PO produksi",
    description=(
        "MENYIAPKAN perubahan tenggat produksi dan/atau tenggat kirim satu atau beberapa PO produksi (nomor PO) — sama "
        "dengan mengubah tanggal tenggat di layar PO Produksi. Hanya tanggal; status, baris, penjahit, dan upah jahit "
        "tidak disentuh.\n"
        "Aturan: izin Ubah PO (aturan tombol Ubah di layar); tanggal baru hari ini atau sesudahnya; PO yang sudah "
        "ditutup terkunci; PO MAKLON yang sudah dikonfirmasi tidak bisa lewat Asisten AI (terhubung ke piutang/hutang) "
        "— hanya draf PO maklon. Bisa dibalikkan: tanggal lama dipulihkan bila belum diubah orang lain. Nomor PO bisa "
        "dilihat dengan pantau_produksi_ringkas."),
    input_schema={
        "type": "object",
        "properties": {
            "po": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {
                "nomor_po": {"type": "string", "minLength": 3, "maxLength": 60, "description": "Nomor PO."},
                "tenggat_produksi": {**TANGGAL, "description": "Tenggat produksi baru (TTTT-BB-HH)."},
                "tenggat_kirim": {**TANGGAL, "description": "Tenggat kirim baru (TTTT-BB-HH)."}},
                "required": ["nomor_po"], "additionalProperties": False}},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["po", "alasan"],
        "additionalProperties": False,
    },
    domain="produksi",
    risiko="menengah",
    menu="prod-pos-internal",
)
class UbahTenggatPoProduksi:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_tenggat(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, sasaran = await _rencana_tenggat(ctx, args)
        selesai: List[dict] = []
        try:
            for s in sasaran:
                await TP._tulis(ctx, "PUT", f"{P_PO}/{s['po_id']}", json=s["patch"])
                selesai.append({"po_id": s["po_id"], "nomor": s["nomor"], "sesudah": s["patch"],
                                "sebelum": s["sebelum"]})
        except AlatError as e:
            gagal = await _tulis_tenggat(ctx, selesai, "sebelum")
            raise TP._gagal_sebagian("Perubahan tenggat", e, gagal) from None

        def _teks(d: dict) -> str:
            return ", ".join(f"{'produksi' if k == 'deadline' else 'kirim'} {_tgl(v)}" for k, v in d.items())
        return {"ringkas": f"Tenggat {len(selesai)} PO diubah: " + "; ".join(
                    f"{e['nomor']} ({_teks(e['sesudah'])})" for e in selesai[:5]) + ".",
                "hasil": {"po": [{"po_id": e["po_id"], "nomor": e["nomor"]} for e in selesai]},
                "sebelum": [{"label": e["nomor"], "nilai": _teks(e["sebelum"]) if any(e["sebelum"].values()) else "—"}
                            for e in selesai],
                "sesudah": [{"label": e["nomor"], "nilai": _teks(e["sesudah"])} for e in selesai],
                "pembatalan": {"po": selesai}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("po") or [])
        beda = []
        for e in entri:
            po = await ctx.api("GET", f"{P_PO}/{e['po_id']}") or {}
            if any(str(po.get(k) or "")[:10] != v for k, v in e["sesudah"].items()):
                beda.append(e["nomor"])
        if beda:
            raise AlatError(409, "Tenggat PO berikut sudah diubah lagi sesudah tindakan ini: " + ", ".join(beda[:8])
                            + ". Pembalikan dibatalkan supaya perubahan itu tidak tertimpa; ubah manual di layar PO.")
        gagal = await _tulis_tenggat(ctx, entri, "sebelum")
        if gagal:
            raise _gagal_balik("tenggat", gagal)
        return {"ringkas": f"Tenggat {len(entri)} PO dikembalikan seperti sebelum tindakan."}


async def _tulis_tenggat(ctx, entri: List[dict], kunci: str) -> List[str]:
    gagal = []
    for e in reversed(entri):
        try:
            await TP._tulis(ctx, "PUT", f"{P_PO}/{e['po_id']}", json={k: e[kunci].get(k) for k in e["sesudah"]})
        except AlatError as x:
            gagal.append(f"{e['nomor']}: {x.pesan}")
    return gagal


# ── draf PO produksi internal ────────────────────────────────────────────────
P_VARIAN = "/api/rahaza/variants"
KUNCI_NOMOR_INTERNAL = "production_pos.po_number"
PELANGGAN_INTERNAL = "Gudang FG Sendiri"        # = isian bawaan layar PO internal


def _waktu_sama(a: Any, b: Any) -> bool:
    """Dua cap waktu sama? Jawaban POST membawa waktu Python (mikrodetik, +00:00), sedangkan Mongo menyimpan
    milidetik tanpa zona — dibandingkan dalam UTC sampai milidetik."""
    def _ms(v: Any) -> Optional[int]:
        if not v:
            return None
        try:
            dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)
    return _ms(a) is not None and _ms(a) == _ms(b)


def _label_varian(v: dict) -> str:
    bagian = [v.get("model_name") or v.get("model_code"), v.get("color_name"), v.get("size_code")]
    return " ".join(str(b) for b in bagian if b)


async def _rencana_draf(ctx, args: dict) -> Tuple[dict, dict]:
    from core import product_status as PS
    TP._cek_cv_tulis(ctx)
    alasan = _alasan(args)
    baris = args["baris"]
    skus = [b["sku"].strip().upper() for b in baris]
    if len(set(skus)) != len(skus):
        raise AlatError(400, "Ada SKU yang disebut dua kali; satukan dulu jumlahnya.")
    for b in baris:
        if float(b["qty"]) != int(b["qty"]) or int(b["qty"]) < 1:
            raise AlatError(400, f"Jumlah SKU {b['sku']} harus bilangan bulat ≥ 1 pcs.")
    await _izin_po(ctx, "internal", "create")
    pol = await ctx.api("GET", "/api/doc-number-policy", params={"key": KUNCI_NOMOR_INTERNAL}) or {}
    manual = pol.get("mode") == "manual"
    if manual and not (args.get("nomor_po") or "").strip():
        raise AlatError(400, f"Penomoran PO produksi internal disetel MANUAL: sebutkan nomor_po (pola "
                             f"{pol.get('format')}, contoh {pol.get('contoh')}).")
    if not manual and (args.get("nomor_po") or "").strip():
        raise AlatError(400, "Penomoran PO produksi internal disetel OTOMATIS: jangan isi nomor_po; nomor dibuat sistem "
                             f"(berikutnya kira-kira {pol.get('nomor_berikutnya') or '—'}).")
    for kunci, _k, nama in KOLOM_TENGGAT:
        if args.get(kunci):
            _tanggal_maju(ctx, args[kunci], nama)
    if args.get("tenggat_produksi") and args.get("tenggat_kirim") and args["tenggat_kirim"] < args["tenggat_produksi"]:
        raise AlatError(400, "Tenggat kirim tidak boleh sebelum tenggat produksi.")
    varian = {str(v.get("sku") or "").strip().upper(): v
              for v in (await ctx.api("GET", P_VARIAN) or []) if v.get("active") is not False}
    tidak_ada = [b["sku"] for b in baris if b["sku"].strip().upper() not in varian]
    if tidak_ada:
        raise AlatError(404, "SKU berikut tidak ada di master varian aktif: " + ", ".join(tidak_ada[:10])
                             + ". PO internal hanya untuk SKU varian produk sendiri (Master Produk).")
    perubahan, peringatan, ubah, items = [], [], [], []
    total = 0
    for i, b in enumerate(baris):
        v = varian[b["sku"].strip().upper()]
        q = int(b["qty"])
        total += q
        items.append({"rahaza_variant_id": v["id"], "sku": v.get("sku"), "qty": q})
        perubahan.append({"label": f"{v.get('sku')} · {_label_varian(v)}"[:150], "sebelum": "—",
                          "sesudah": f"{TP.angka(q)} pcs"})
        ubah.append({"kunci": f"baris.{i}.qty", "label": f"Jumlah {v.get('sku')}", "jenis": "angka", "nilai": q})
        if v.get(PS.FIELD) == PS.STOP:
            peringatan.append(f"SKU {v.get('sku')}: {PS.STOP_REASON}.")
    for kunci, _k, nama in KOLOM_TENGGAT:
        if args.get(kunci):
            perubahan.append({"label": nama, "sebelum": "—", "sesudah": _tgl(args[kunci])})
            ubah.append({"kunci": kunci, "label": nama, "jenis": "tanggal", "nilai": args[kunci]})
    perubahan.append({"label": "Total", "sebelum": "—", "sesudah": f"{TP.angka(total)} pcs ({len(baris)} SKU)"})
    if not args.get("tenggat_produksi"):
        peringatan.append("Tenggat produksi belum diisi; PO tanpa tenggat tidak terpantau telat di Pantau Produksi.")
    ubah.insert(0, _ubah_alasan(args))
    nomor = (args.get("nomor_po") or "").strip() or None
    catatan = [f"Dibuat sebagai DRAF (belum dikonfirmasi). Nomor: {nomor or (pol.get('nomor_berikutnya') or 'otomatis')}"
               + ("" if nomor else " (perkiraan; nomor pasti saat disimpan)") + ".",
               "Konfirmasi PO tetap dilakukan orang yang berwenang di layar PO Produksi Internal; Asisten AI tidak "
               "pernah mengonfirmasi atau merilis PO.",
               "Penjahit (CMT) dan upah jahit diisi belakangan di layar PO, seperti biasa. Kebutuhan aksesoris dari BOM "
               "dihitung otomatis saat draf disimpan."]
    if str(ctx.cv).upper() == "SMU":
        catatan.append("PO produksi internal milik CV DA.")
    notes = "Draf dibuat lewat Asisten AI. Alasan: " + alasan + (f"\n{args['catatan']}" if args.get("catatan") else "")
    body = {"business_type": "internal", "customer_name": PELANGGAN_INTERNAL, "po_number": nomor or "",
            "po_date": B.hari_ini(ctx).isoformat(), "deadline": args.get("tenggat_produksi") or None,
            "delivery_deadline": args.get("tenggat_kirim") or None, "notes": notes[:1000], "items": items}
    return TP._batasi({
        "judul": "Buat draf PO produksi internal",
        "ringkas": f"{len(baris)} SKU, total {TP.angka(total)} pcs"
                   + (f", tenggat produksi {_tgl(args['tenggat_produksi'])}." if args.get("tenggat_produksi") else "."),
        "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
        "tautan": {"label": "Buka layar PO Produksi Internal", "menu": "prod-pos-internal"}}), body


@tindakan(
    name="buat_draf_po_produksi",
    label="Membuat draf PO produksi",
    description=(
        "MENYIAPKAN DRAF PO produksi internal (produk sendiri, Gudang FG) dari daftar SKU varian + jumlah pcs, dengan "
        "tenggat produksi/kirim opsional — sama dengan tombol Buat PO di layar PO Produksi Internal. Hanya DRAF: tidak "
        "pernah mengonfirmasi atau merilis PO; konfirmasi tetap oleh orang yang berwenang di layar. Bukan PO maklon.\n"
        "Aturan: izin Tambah PO (aturan tombol Buat PO); SKU harus varian aktif di Master Produk; jumlah bilangan bulat; "
        "tenggat hari ini atau sesudahnya. nomor_po hanya bila penomoran disetel manual. Penjahit dan upah jahit diisi "
        "belakangan di layar. Bisa dibalikkan: draf dihapus selama masih draf yang belum diubah siapa pun."),
    input_schema={
        "type": "object",
        "properties": {
            "baris": {"type": "array", "minItems": 1, "maxItems": 50, "items": {"type": "object", "properties": {
                "sku": {"type": "string", "minLength": 2, "maxLength": 80, "description": "SKU varian."},
                "qty": {"type": "integer", "minimum": 1, "maximum": 100000, "description": "Jumlah (pcs)."}},
                "required": ["sku", "qty"], "additionalProperties": False}},
            "tenggat_produksi": {**TANGGAL, "description": "Tenggat produksi (TTTT-BB-HH, opsional)."},
            "tenggat_kirim": {**TANGGAL, "description": "Tenggat kirim (TTTT-BB-HH, opsional)."},
            "catatan": {"type": "string", "maxLength": 500, "description": "Catatan PO (opsional)."},
            "nomor_po": {"type": "string", "minLength": 3, "maxLength": 60,
                         "description": "Hanya bila penomoran PO internal disetel manual."},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["baris", "alasan"],
        "additionalProperties": False,
    },
    domain="produksi",
    risiko="menengah",
    menu="prod-pos-internal",
)
class BuatDrafPoProduksi:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_draf(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, body = await _rencana_draf(ctx, args)
        res = await TP._tulis(ctx, "POST", P_PO, json=body) or {}
        if res.get("status") != "Draft":      # pertahanan: alat ini tidak pernah mengirim status
            raise AlatError(500, f"PO {res.get('po_number')} tersimpan dengan status {res.get('status')}, bukan draf. "
                                 "Periksa layar PO.")
        acc = res.get("accessories_explode") or {}
        total = sum(int(i["qty"]) for i in body["items"])
        return {"ringkas": f"Draf PO {res.get('po_number')} dibuat ({len(body['items'])} SKU, {TP.angka(total)} pcs). "
                           "Konfirmasi tetap di layar PO Produksi Internal.",
                "hasil": {"po_id": res.get("id"), "po_number": res.get("po_number"), "status": "Draf",
                          "aksesoris_dari_bom": {k: acc.get(k) for k in ("created", "updated", "skipped", "missing_bom")
                                                 if k in acc} or None},
                "pembatalan": {"po_id": res.get("id"), "po_number": res.get("po_number"),
                               "updated_at": res.get("updated_at")}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        pid, nomor = pembatalan["po_id"], pembatalan.get("po_number") or "PO"
        try:
            po = await ctx.api("GET", f"{P_PO}/{pid}") or {}
        except AlatError as e:
            if e.status == 404:
                return {"ringkas": f"Draf PO {nomor} sudah tidak ada (sudah dihapus)."}
            raise
        if po.get("status") != "Draft":
            raise AlatError(409, f"PO {nomor} sudah {STATUS_PO.get(po.get('status'), po.get('status')).lower()}, jadi "
                                 "tidak dihapus otomatis. Tangani di layar PO.")
        if po.get("distributions") or not _waktu_sama(po.get("updated_at"), pembatalan.get("updated_at")):
            raise AlatError(409, f"Draf PO {nomor} sudah diubah atau sudah dipakai sesudah tindakan ini, jadi tidak "
                                 "dihapus otomatis. Hapus manual di layar PO bila memang perlu.")
        try:
            await TP._tulis(ctx, "DELETE", f"{P_PO}/{pid}")
        except AlatError as e:
            if e.status == 403:
                raise AlatError(403, f"Akun Anda tidak boleh menghapus PO (bawaannya owner/admin). Minta mereka menekan "
                                     f"Balikkan atau menghapus draf {nomor} di layar PO.") from None
            raise
        return {"ringkas": f"Draf PO {nomor} dihapus."}


# ══════════════════════════════════════════════════════════════════════════════
# 4. AMBANG STOK / TITIK PESAN ULANG
# ══════════════════════════════════════════════════════════════════════════════
P_AMBANG = "/api/rahaza/stock-thresholds"
LABEL_STATUS_STOK = {"no_threshold": "tanpa ambang", "critical": "kritis", "low": "menipis", "ok": "aman"}


def _cek_penulis_ambang(ctx) -> None:
    """Cermin `routes.rahaza_inventory_shared._require_admin` (penjaga simpan Ambang Stok; endpoint tetap penjaga
    sebenarnya)."""
    role = str(ctx.user.get("role") or "").lower()
    perms = ctx.user.get("_permissions") or []
    if role in ("superadmin", "admin", "owner") or "*" in perms or "inventory.manage" in perms \
            or "warehouse.manage" in perms:
        return
    raise AlatError(403, "Akun Anda tidak boleh mengubah ambang stok: itu wewenang owner/admin atau peran yang diberi "
                         "izin kelola gudang/persediaan (layar Ambang Stok).")


async def _cari_barang(ctx, kode: str) -> dict:
    k = kode.strip()
    d = await ctx.api("GET", P_AMBANG, params={"search": k[:60], "limit": 50}) or {}
    rows = d.get("items") or []
    persis = [r for r in rows if str(r.get("code") or "").strip().upper() == k.upper()] or \
        [r for r in rows if str(r.get("name") or "").strip().upper() == k.upper()]
    if len(persis) == 1:
        return persis[0]
    if len(persis) > 1:
        raise AlatError(400, f"'{k}' cocok dengan beberapa barang: " + ", ".join(
            f"{r.get('code')} ({r.get('name')})" for r in persis[:6]) + ". Sebutkan kodenya.")
    mirip = ", ".join(f"{r.get('code')} ({r.get('name')})" for r in rows[:5])
    raise AlatError(404, f"Barang berkode '{k}' tidak ditemukan" + (f". Yang mirip: {mirip}." if mirip else
                                                                    ". Periksa kodenya di layar Ambang Stok."))


def _teks_ambang(min_q: float, rp_q: float, onhand: float, unit: str, status: str) -> str:
    u = f" {unit}" if unit else ""
    return (f"min {_q(min_q) + u if min_q else '—'} · pesan ulang {_q(rp_q) + u if rp_q else '—'} · stok "
            f"{_q(onhand)}{u} ({LABEL_STATUS_STOK.get(status, status)})")


async def _rencana_ambang(ctx, args: dict) -> Tuple[dict, List[dict]]:
    from core import stock_thresholds as TH
    TP._cek_cv_tulis(ctx)
    _alasan(args)
    _cek_penulis_ambang(ctx)
    perubahan, peringatan, catatan, ubah, sasaran = [], [], [], [], []
    dipakai = set()
    for i, b in enumerate(args["barang"]):
        if b.get("titik_pesan_ulang") is None and b.get("stok_minimum") is None:
            raise AlatError(400, f"Sebutkan titik_pesan_ulang dan/atau stok_minimum baru untuk {b['kode']}.")
        r = await _cari_barang(ctx, b["kode"])
        if r["material_id"] in dipakai:
            raise AlatError(400, f"Barang {r.get('code')} disebut dua kali; satukan dulu angkanya.")
        dipakai.add(r["material_id"])
        lama = {"min_stock_qty": _bulat(r.get("min_stock_qty")), "reorder_point": _bulat(r.get("reorder_point"))}
        baru = dict(lama)
        if b.get("stok_minimum") is not None:
            baru["min_stock_qty"] = _bulat(b["stok_minimum"])
        if b.get("titik_pesan_ulang") is not None:
            baru["reorder_point"] = _bulat(b["titik_pesan_ulang"])
        kolom = [k for k in ("min_stock_qty", "reorder_point") if baru[k] != lama[k]]
        if b.get("stok_minimum") is not None:
            ubah.append({"kunci": f"barang.{i}.stok_minimum", "label": f"Stok minimum {r.get('code')}", "jenis": "angka",
                         "nilai": b["stok_minimum"]})
        if b.get("titik_pesan_ulang") is not None:
            ubah.append({"kunci": f"barang.{i}.titik_pesan_ulang", "label": f"Titik pesan ulang {r.get('code')}",
                         "jenis": "angka", "nilai": b["titik_pesan_ulang"]})
        if not kolom:
            continue
        legacy = {"min_stock": r.get("min_stock_legacy"), "min_stock_percentage": r.get("min_stock_percentage")}
        th_baru = TH.resolve_threshold({**legacy, **baru})
        onhand, unit = float(r.get("onhand") or 0), r.get("unit") or ""
        st_baru = TH.status_of(onhand, th_baru)
        nama = f"{r.get('code')} {str(r.get('name') or '')[:50]}".strip()
        perubahan.append({"label": nama,
                          "sebelum": _teks_ambang(r.get("min_qty") or 0, r.get("reorder_point") or 0, onhand, unit,
                                                  r.get("status")),
                          "sesudah": _teks_ambang(th_baru["min_qty"], th_baru["reorder_point"], onhand, unit, st_baru)})
        if th_baru["min_qty"] and th_baru["reorder_point"] and th_baru["reorder_point"] < th_baru["min_qty"]:
            peringatan.append(f"{r.get('code')}: titik pesan ulang lebih kecil dari stok minimum, jadi tanda 'menipis' "
                              "tidak akan muncul sebelum 'kritis'.")
        if "min_stock_qty" in kolom and not baru["min_stock_qty"] and _bulat(r.get("min_stock_legacy")):
            catatan.append(f"{r.get('code')}: stok minimum dikosongkan, jadi kembali memakai angka minimum lama dari Master "
                           f"Aksesoris ({_q(r.get('min_stock_legacy'))} {unit}).")
        sug = r.get("suggestion") or {}
        if sug and not sug.get("no_usage_data"):
            catatan.append(f"{r.get('code')}: usulan dari pemakaian 30 hari — minimum {_q(sug.get('suggested_min_stock'))}, "
                           f"pesan ulang {_q(sug.get('suggested_reorder_point'))} {unit}.")
        sasaran.append({"material_id": r["material_id"], "kode": r.get("code"), "kolom": kolom, "sebelum": lama,
                        "sesudah": baru})
    if not sasaran:
        raise AlatError(409, "Ambang barang itu sudah sama persis dengan isian ini; tidak ada yang perlu diubah.")
    ubah.insert(0, _ubah_alasan(args))
    catatan = ["Hanya ambang yang berubah; jumlah stok TIDAK disentuh. Angka 0 = ambang itu dikosongkan.",
               "Status menipis/kritis di layar Ambang Stok, Alert & Reorder, notifikasi, dan Daftar Belanja Mingguan ikut "
               "ambang baru."] + catatan[:8]
    if str(ctx.cv).upper() == "SMU":
        catatan.append("Bahan dan stok dicatat di CV DA; ambang berlaku untuk gudang yang sama.")
    return TP._batasi({
        "judul": "Ubah ambang stok" if len(sasaran) > 1 else f"Ubah ambang stok {sasaran[0]['kode']}",
        "ringkas": f"{len(sasaran)} barang — stok minimum / titik pesan ulang diubah.",
        "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
        "tautan": {"label": "Buka layar Master Barang › Ambang Stok", "menu": "wh-master"}}), sasaran


async def _simpan_ambang(ctx, entri: List[dict], kunci: str):
    items = [{"material_id": e["material_id"], **{k: e[kunci][k] for k in e["kolom"]}} for e in entri]
    return await TP._tulis(ctx, "POST", f"{P_AMBANG}/bulk", json={"items": items})


@tindakan(
    name="ubah_titik_pesan_ulang",
    label="Mengubah ambang stok",
    description=(
        "MENYIAPKAN perubahan stok minimum dan/atau titik pesan ulang satu atau beberapa barang (bahan, aksesoris, "
        "barang jadi; kode barang) — sama dengan layar Ambang Stok. HANYA ambang peringatan; jumlah stok tidak pernah "
        "diubah (penyesuaian stok bukan untuk Asisten AI). Kartu menampilkan ambang lama → baru dan status stok "
        "sesudahnya (aman/menipis/kritis); 0 = kosongkan.\n"
        "Aturan: owner/admin atau izin kelola gudang/persediaan. Bisa dibalikkan: ambang lama dipulihkan bila belum "
        "diubah orang lain. Barang menipis bisa dilihat dengan stok_menipis."),
    input_schema={
        "type": "object",
        "properties": {
            "barang": {"type": "array", "minItems": 1, "maxItems": 50, "items": {"type": "object", "properties": {
                "kode": {"type": "string", "minLength": 2, "maxLength": 80, "description": "Kode barang."},
                "titik_pesan_ulang": {"type": "number", "minimum": 0, "maximum": 1e8,
                                      "description": "Titik pesan ulang baru (satuan barang)."},
                "stok_minimum": {"type": "number", "minimum": 0, "maximum": 1e8,
                                 "description": "Stok minimum baru (satuan barang)."}},
                "required": ["kode"], "additionalProperties": False}},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["barang", "alasan"],
        "additionalProperties": False,
    },
    domain="stok",
    risiko="menengah",
    menu="wh-master",
)
class UbahTitikPesanUlang:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_ambang(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, sasaran = await _rencana_ambang(ctx, args)
        await _simpan_ambang(ctx, sasaran, "sesudah")

        def _teks(d: dict) -> str:
            return f"min {_q(d['min_stock_qty']) if d['min_stock_qty'] else '—'} · pesan ulang " \
                   f"{_q(d['reorder_point']) if d['reorder_point'] else '—'}"
        return {"ringkas": f"Ambang {len(sasaran)} barang diubah: "
                           + ", ".join(e["kode"] for e in sasaran[:8]) + ("…" if len(sasaran) > 8 else "") + ".",
                "hasil": {"barang": [e["kode"] for e in sasaran]},
                "sebelum": [{"label": e["kode"], "nilai": _teks(e["sebelum"])} for e in sasaran],
                "sesudah": [{"label": e["kode"], "nilai": _teks(e["sesudah"])} for e in sasaran],
                "pembatalan": {"barang": sasaran}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("barang") or [])
        beda = []
        for e in entri:
            try:
                r = await _cari_barang(ctx, e["kode"])
            except AlatError:
                beda.append(f"{e['kode']} (barang tidak ditemukan)")
                continue
            if r.get("material_id") != e["material_id"] or any(
                    _bulat(r.get(k)) != _bulat(e["sesudah"][k]) for k in e["kolom"]):
                beda.append(e["kode"])
        if beda:
            raise AlatError(409, "Ambang barang berikut sudah diubah lagi sesudah tindakan ini: " + ", ".join(beda[:8])
                            + ". Pembalikan dibatalkan supaya perubahan itu tidak tertimpa; ubah manual di layar Ambang "
                              "Stok.")
        await _simpan_ambang(ctx, entri, "sebelum")
        return {"ringkas": f"Ambang {len(entri)} barang dikembalikan seperti sebelum tindakan."}


# ══════════════════════════════════════════════════════════════════════════════
# 5. TUTUP / BUKA BULAN MARKETING (kunci periode Siklus Marketing)
# ══════════════════════════════════════════════════════════════════════════════
P_KUNCI = "/api/marketing/periods/lock"
P_DAFTAR_KUNCI = "/api/marketing/periods/locks"


async def _terkunci(ctx, bulan: str) -> set:
    data = await ctx.api("GET", P_DAFTAR_KUNCI) or {}
    return {r.get("account_id") for r in data.get("locks") or [] if r.get("locked") and r.get("period") == bulan}


async def _rencana_periode(ctx, args: dict) -> Tuple[dict, List[dict]]:
    from core.marketing_cycle import can_manage_period
    TP._cek_cv_tulis(ctx)
    _alasan(args)
    if not can_manage_period(ctx.user):
        raise AlatError(403, "Hanya SPV/Manager Marketing, akunting, atau owner yang boleh menutup dan membuka periode "
                             "marketing (aturan layar Siklus Marketing).")
    aksi, bulan = args["aksi"], args["bulan"]
    label = U.label_bulan(bulan)
    kini = B.bulan_ini(ctx)
    if aksi == "tutup" and bulan > kini:
        raise AlatError(400, f"{label} belum berjalan, jadi belum bisa ditutup.")
    terlihat = await TP._toko_cv(ctx, bulan)
    ids = list(dict.fromkeys(args.get("toko_id") or list(terlihat)))
    if not ids:
        raise AlatError(404, "Tidak ada toko yang bisa dipakai akun ini pada CV terpilih.")
    TP._tolak_toko_luar(ctx, ids, terlihat)
    kunci = await _terkunci(ctx, bulan)
    mau_kunci = aksi == "tutup"
    sasaran = [{"toko_id": i, "toko": terlihat[i].get("toko") or i} for i in ids if (i in kunci) != mau_kunci]
    lewat = [terlihat[i].get("toko") or i for i in ids if (i in kunci) == mau_kunci]
    if not sasaran:
        raise AlatError(409, f"Periode {label} untuk toko itu sudah {'ditutup' if mau_kunci else 'terbuka'} semua.")
    st_lama, st_baru = ("Terbuka", "Ditutup") if mau_kunci else ("Ditutup", "Terbuka")
    perubahan = [{"label": s["toko"], "sebelum": f"{label}: {st_lama}", "sesudah": f"{label}: {st_baru}"}
                 for s in sasaran]
    peringatan = []
    if mau_kunci and bulan == kini:
        peringatan.append(f"{label} masih berjalan: rekap harian, target, rencana anggaran, dan belanja manual bulan ini "
                          "ikut terkunci sampai periodenya dibuka lagi.")
    if not mau_kunci:
        peringatan.append("Membuka periode berarti angka bulan yang sudah dirapatkan bisa berubah lagi.")
    catatan = [("Saat ditutup, target, rencana anggaran, belanja manual, dan rekap harian toko itu untuk bulan tersebut "
                "tidak bisa diubah sampai dibuka lagi.") if mau_kunci else
               "Sesudah dibuka, target, anggaran, belanja manual, dan rekap harian bulan itu bisa diubah lagi.",
               "Tercatat di Jejak Perubahan (Kunci periode) dengan alasan dan tanda 'Asisten AI'. Ini kunci periode "
               "MARKETING, bukan tutup buku akuntansi."]
    if lewat:
        catatan.append(f"Sudah {'ditutup' if mau_kunci else 'terbuka'} (dilewati): " + ", ".join(lewat[:10]) + ".")
    return TP._batasi({
        "judul": f"{'Tutup' if mau_kunci else 'Buka'} periode marketing {label}",
        "ringkas": f"{len(sasaran)} toko akan {'ditutup' if mau_kunci else 'dibuka'} untuk {label}.",
        "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": [_ubah_alasan(args)],
        "tautan": {"label": "Buka layar Target & Siklus", "menu": "marketing-targets"}}), sasaran


async def _set_kunci(ctx, bulan: str, entri: List[dict], aksi: str, alasan: str) -> List[str]:
    gagal = []
    for e in reversed(entri):
        try:
            await TP._tulis(ctx, "POST", P_KUNCI, json={"account_id": e["toko_id"], "period": bulan,
                                                        "action": "close" if aksi == "tutup" else "reopen",
                                                        "reason": alasan})
        except AlatError as x:
            gagal.append(f"{e['toko']}: {x.pesan}")
    return gagal


@tindakan(
    name="tutup_buka_bulan_marketing",
    label="Menutup atau membuka bulan marketing",
    description=(
        "MENYIAPKAN penutupan atau pembukaan kembali periode bulanan MARKETING per toko (Siklus Marketing: tombol Tutup/"
        "Buka Periode). Saat ditutup, target, rencana anggaran, belanja manual, dan rekap harian toko itu untuk bulan "
        "tersebut terkunci. Ini BUKAN tutup buku akuntansi.\n"
        "toko_id kosong = semua toko yang Anda pegang pada CV terpilih; toko yang sudah dalam keadaan itu dilewati. "
        "Aturan: SPV/Manager Marketing, akunting, atau owner; bulan yang belum berjalan tidak bisa ditutup; alasan "
        "wajib dan tercatat di Jejak Perubahan. Bisa dibalikkan: keadaan kunci lama dipulihkan bila belum diubah "
        "orang lain."),
    input_schema={
        "type": "object",
        "properties": {
            "aksi": {"type": "string", "enum": ["tutup", "buka"]},
            "bulan": {**BULAN, "description": "Bulan (TTTT-BB)."},
            "toko_id": {"type": "array", "minItems": 1, "maxItems": 30,
                        "items": {"type": "string", "minLength": 1}, "description": "Id toko (opsional)."},
            "alasan": ALASAN_WAJIB,
        },
        "required": ["aksi", "bulan", "alasan"],
        "additionalProperties": False,
    },
    domain="penjualan",
    risiko="menengah",
    menu="marketing-targets",
)
class TutupBukaBulanMarketing:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        rencana, _ = await _rencana_periode(ctx, args)
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _r, sasaran = await _rencana_periode(ctx, args)
        aksi, bulan = args["aksi"], args["bulan"]
        selesai: List[dict] = []
        try:
            for s in sasaran:
                await TP._tulis(ctx, "POST", P_KUNCI, json={"account_id": s["toko_id"], "period": bulan,
                                                            "action": "close" if aksi == "tutup" else "reopen",
                                                            "reason": TP._jejak(_alasan(args))})
                selesai.append(s)
        except AlatError as e:
            gagal = await _set_kunci(ctx, bulan, selesai, "buka" if aksi == "tutup" else "tutup",
                                     TP._jejak("dibatalkan otomatis: tindakan gagal"))
            raise TP._gagal_sebagian("Kunci periode", e, gagal) from None
        kata = "ditutup" if aksi == "tutup" else "dibuka"
        return {"ringkas": f"Periode {U.label_bulan(bulan)} {kata} untuk {len(selesai)} toko.",
                "hasil": {"bulan": bulan, "aksi": aksi, "toko": [s["toko"] for s in selesai]},
                "pembatalan": {"bulan": bulan, "aksi": aksi, "toko": selesai}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        bulan, aksi, entri = pembatalan["bulan"], pembatalan["aksi"], list(pembatalan.get("toko") or [])
        kunci = await _terkunci(ctx, bulan)
        beda = [e["toko"] for e in entri if (e["toko_id"] in kunci) != (aksi == "tutup")]
        if beda:
            raise AlatError(409, f"Kunci periode {U.label_bulan(bulan)} toko berikut sudah diubah lagi sesudah tindakan "
                                 "ini: " + ", ".join(beda[:8]) + ". Pembalikan dibatalkan.")
        gagal = await _set_kunci(ctx, bulan, entri, "buka" if aksi == "tutup" else "tutup",
                                 TP._jejak("membalikkan tindakan"))
        if gagal:
            raise _gagal_balik("kunci periode", gagal)
        return {"ringkas": f"Periode {U.label_bulan(bulan)} {len(entri)} toko dikembalikan "
                           f"({'dibuka lagi' if aksi == 'tutup' else 'ditutup lagi'})."}
