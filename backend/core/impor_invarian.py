"""core.impor_invarian — **uji rumus sebagai HAKIM pemetaan kolom uang** (riset §7.4).

KENAPA (9 Nov 2026, agen MKT-AI)
--------------------------------
Pemetaan kolom uang tidak boleh dipercaya hanya karena namanya mirip — kamus maupun AI bisa
salah, dan salahnya baru terlihat di laporan bulanan. Ekspor marketplace membawa RUMUS yang
terbukti di berkas asli (674/674 baris SKU TikTok, 559/559 pesanan, 154/154 baris Shopee):

| laporan            | rumus                                                                        |
|--------------------|------------------------------------------------------------------------------|
| TikTok pesanan     | sesudah = sebelum − diskon platform − diskon penjual (per baris)             |
| TikTok pesanan     | Order Amount = Σ sesudah + ongkir + Σ biaya layanan + penanganan + asuransi − diskon bayar |
| Shopee pesanan     | Subtotal = Harga Setelah Diskon × Jumlah                                      |
| Shopee pesanan     | Total Diskon = Diskon Penjual + Diskon Shopee = (Harga Awal − HSD) × Jumlah  |
| Iklan CPC Shopee   | CTR ≈ klik ÷ dilihat · ROAS ≈ omzet ÷ biaya · ACOS ≈ biaya ÷ omzet          |
| TikTok GMV Max     | biaya per pesanan ≈ biaya ÷ pesanan                                          |

Modul ini menjalankan rumus itu atas baris yang SUDAH dikonversi mesin impor (gaya angka per
kolom ikut dipakai), sehingga satu pemetaan kolom uang baru boleh dipakai hanya bila rumus yang
menyentuh kolom itu lolos ≥ 98 % baris. Gagal ⇒ baris yang gagal + kolom tersangka dilaporkan.

Tanpa database, tanpa AI.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from core import marketing_import_engine as eng
from core.marketing_import_schema import SourceType

AMBANG_LOLOS = 98.0           # % baris yang wajib cocok
TOL_RUPIAH = 1.0              # selisih pembulatan
TOL_RASIO = 0.02              # 2 % relatif untuk rasio (CTR/ROAS/ACOS dibulatkan platform)


def _f(d: dict, k: str) -> Optional[float]:
    v = d.get(k)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _hampir(a: float, b: float, *, rasio: bool = False) -> bool:
    if rasio:
        return abs(a - b) <= max(0.05, abs(b) * TOL_RASIO)
    return abs(a - b) <= TOL_RUPIAH


class Rumus:
    """Satu invarian. ``per`` = "baris" (data hasil konversi per baris berkas) atau "pesanan"
    (daftar baris yang dikelompokkan nomor pesanan)."""

    def __init__(self, kode: str, teks: str, fields: Tuple[str, ...], fn: Callable, per: str = "baris",
                 wajib: Tuple[str, ...] = ()):
        self.kode, self.teks, self.fields, self.fn, self.per = kode, teks, fields, fn, per
        self.wajib = wajib or fields      # field yang harus terpetakan supaya rumus bisa diuji


def _tt_sku(d):
    b, p, s, a = (_f(d, k) for k in ("sku_subtotal_before_discount", "sku_platform_discount",
                                     "sku_seller_discount", "sku_subtotal_after_all_discount"))
    if None in (b, a):
        return None
    return _hampir(b - (p or 0) - (s or 0), a)


def _tt_order(rows):
    r0 = rows[0]
    oa = _f(r0, "order_amount")
    if oa is None:
        return None
    est = sum(_f(r, "sku_subtotal_after_all_discount") or 0 for r in rows)
    est += sum(_f(r, "buyer_service_fee") or 0 for r in rows)
    for k in ("shipping_fee_after_discount", "handling_fee", "shipping_insurance", "item_insurance"):
        est += _f(r0, k) or 0
    est -= _f(r0, "payment_platform_discount") or 0
    return _hampir(est, oa)


def _sp_subtotal(d):
    a, h, q = _f(d, "sku_subtotal_after_all_discount"), _f(d, "sku_unit_deal_price"), _f(d, "quantity")
    if None in (a, h, q):
        return None
    return _hampir(h * q, a)


def _sp_diskon(d):
    t, s, p = _f(d, "total_discount"), _f(d, "sku_seller_discount"), _f(d, "sku_platform_discount")
    if t is None or s is None:
        return None
    return _hampir((s or 0) + (p or 0), t)


def _sp_diskon_harga(d):
    t, o, h, q = (_f(d, k) for k in ("total_discount", "sku_unit_original_price", "sku_unit_deal_price", "quantity"))
    if None in (t, o, h, q):
        return None
    return _hampir((o - h) * q, t)


def _cpc_ctr(d):
    c, i, k = _f(d, "ctr_platform"), _f(d, "impressions"), _f(d, "clicks")
    if None in (c, i, k) or i <= 0:
        return None
    return _hampir(k / i * 100, c, rasio=True)


def _cpc_roas(d):
    r, rev, sp = _f(d, "roas_platform"), _f(d, "revenue"), _f(d, "spend")
    if None in (r, rev, sp) or sp <= 0:
        return None
    return _hampir(rev / sp, r, rasio=True)


def _cpc_acos(d):
    a, rev, sp = _f(d, "acos"), _f(d, "revenue"), _f(d, "spend")
    if None in (a, rev, sp) or rev <= 0:
        return None
    return _hampir(sp / rev * 100, a, rasio=True)


def _gmv_cpo(d):
    cpo, sp, n = _f(d, "cost_per_order"), _f(d, "spend"), _f(d, "conversions")
    if None in (cpo, sp, n) or n <= 0:
        return None
    return _hampir(sp / n, cpo)


RUMUS: Dict[str, Tuple[Rumus, ...]] = {
    "marketplace_orders": (
        Rumus("sku_sesudah", "Subtotal sesudah diskon = sebelum − diskon platform − diskon penjual",
              ("sku_subtotal_before_discount", "sku_platform_discount", "sku_seller_discount",
               "sku_subtotal_after_all_discount"), _tt_sku,
              wajib=("sku_subtotal_before_discount", "sku_seller_discount", "sku_subtotal_after_all_discount")),
        Rumus("order_amount", "Order Amount = Σ subtotal sesudah diskon + ongkir + Σ biaya layanan + penanganan + "
                              "asuransi − diskon pembayaran platform",
              ("order_amount", "sku_subtotal_after_all_discount", "buyer_service_fee",
               "shipping_fee_after_discount", "handling_fee", "shipping_insurance", "item_insurance",
               "payment_platform_discount"), _tt_order, per="pesanan",
              wajib=("order_amount", "sku_subtotal_after_all_discount")),
        Rumus("subtotal_harga", "Subtotal = harga setelah diskon × jumlah",
              ("sku_subtotal_after_all_discount", "sku_unit_deal_price", "quantity"), _sp_subtotal),
        Rumus("total_diskon", "Total diskon = diskon penjual + diskon platform",
              ("total_discount", "sku_seller_discount", "sku_platform_discount"), _sp_diskon,
              wajib=("total_discount", "sku_seller_discount")),
        Rumus("total_diskon_harga", "Total diskon = (harga awal − harga setelah diskon) × jumlah",
              ("total_discount", "sku_unit_original_price", "sku_unit_deal_price", "quantity"), _sp_diskon_harga),
    ),
    "shopee_ads_cpc": (
        Rumus("ctr", "Persentase klik ≈ klik ÷ dilihat", ("ctr_platform", "impressions", "clicks"), _cpc_ctr),
        Rumus("roas", "Efektivitas iklan ≈ omzet ÷ biaya", ("roas_platform", "revenue", "spend"), _cpc_roas),
        Rumus("acos", "ACOS ≈ biaya ÷ omzet", ("acos", "revenue", "spend"), _cpc_acos),
    ),
    "tiktok_gmv_max": (
        Rumus("cpo", "Biaya per pesanan ≈ biaya ÷ pesanan", ("cost_per_order", "spend", "conversions"), _gmv_cpo),
    ),
}
# jenis impor yang memakai rumus jenis lain (mis. "ads" rekap ketikan tidak punya rumus)
RUMUS_ALIAS: Dict[str, str] = {"ads": "tiktok_gmv_max"}


def rumus_untuk(st_key: str) -> Tuple[Rumus, ...]:
    return RUMUS.get(st_key) or RUMUS.get(RUMUS_ALIAS.get(st_key, ""), ()) or ()


def baris_kanonik(rows: Sequence[dict], mapping: List[dict], st: SourceType) -> List[dict]:
    """Baris berkas → data kanonik per baris (TANPA pengelompokan), dengan profil kolom yang
    sama dengan mesin impor (gaya angka seluruh kolom)."""
    used = eng.mapping_dict(mapping)
    prof = eng.profil_kolom(list(rows), used, st)
    out = []
    for r in rows:
        d, _e, _w = eng._coerce_row(r, used, st, None, prof)
        out.append(d)
    return out


def uji(st: SourceType, rows: Sequence[dict], mapping: List[dict], *,
        hanya_fields: Optional[Iterable[str]] = None, maks_contoh: int = 8) -> List[dict]:
    """Jalankan semua rumus jenis ``st`` yang bisa diuji dengan pemetaan ``mapping``.

    ``hanya_fields`` = batasi pada rumus yang menyentuh salah satu field ini (hakim usulan).
    → ``[{kode, rumus, diuji, lolos, persen, lulus, gagal_contoh[], kolom_tersangka[]}]``."""
    rumus = rumus_untuk(st.key)
    if not rumus:
        return []
    used = eng.mapping_dict(mapping)
    mapped = set(used.values())
    col_of = {f: c for c, f in used.items()}
    fokus = set(hanya_fields or ())
    data = None
    hasil = []
    for ru in rumus:
        if fokus and not (fokus & set(ru.fields)):
            continue
        if not set(ru.wajib) <= mapped:
            continue
        if data is None:
            data = baris_kanonik(rows, mapping, st)
        diuji = lolos = 0
        gagal = []
        if ru.per == "pesanan":
            grup: Dict[str, List[Tuple[int, dict]]] = {}
            for i, d in enumerate(data):
                oid = str(d.get("order_id") or "")
                if oid:
                    grup.setdefault(oid, []).append((i, d))
            unit = [(g[0][0], [d for _, d in g]) for g in grup.values()]
        else:
            unit = list(enumerate(data))
        for i, u in unit:
            ok = ru.fn(u)
            if ok is None:
                continue
            diuji += 1
            if ok:
                lolos += 1
            elif len(gagal) < maks_contoh:
                gagal.append({"baris_berkas": i + 2})
        persen = round(lolos / diuji * 100, 1) if diuji else None
        hasil.append({
            "kode": ru.kode, "rumus": ru.teks, "diuji": diuji, "lolos": lolos, "persen": persen,
            "lulus": bool(diuji) and persen >= AMBANG_LOLOS,
            "gagal_contoh": gagal,
            "kolom_tersangka": [col_of[f] for f in ru.fields if f in col_of] if diuji and persen < AMBANG_LOLOS else [],
        })
    return hasil


def hakim_usulan(st: SourceType, rows: Sequence[dict], mapping: List[dict],
                 usulan: Dict[str, str]) -> Dict[str, dict]:
    """Putusan per kolom usulan UANG: ``{kolom: {diterima, alasan, invarian[]}}``.

    Usulan diterapkan ke salinan pemetaan lalu rumus yang menyentuh field usulan dijalankan.
    * semua rumus yang bisa diuji lulus ⇒ diterima;
    * ada rumus gagal ⇒ ditolak (kolom tersangka disebut);
    * tidak ada rumus yang bisa menguji ⇒ ditolak dengan alasan "tidak bisa diuji" — kolom uang
      tanpa bukti rumus hanya boleh dipetakan manual oleh staf."""
    out: Dict[str, dict] = {}
    if not usulan:
        return out
    trial = [dict(m) for m in mapping]
    by_col = {m.get("column"): m for m in trial}
    for col, fld in usulan.items():
        if col in by_col:
            by_col[col].update({"field": fld, "method": "ai"})
        else:
            trial.append({"column": col, "field": fld, "method": "ai"})
    for col, fld in usulan.items():
        res = uji(st, rows, trial, hanya_fields=[fld])
        if not res:
            out[col] = {"diterima": False, "invarian": [],
                        "alasan": "Kolom uang ini tidak bisa diuji dengan rumus laporan yang diketahui — "
                                  "petakan manual bila Anda yakin."}
            continue
        gagal = [r for r in res if not r["lulus"]]
        if gagal:
            g = gagal[0]
            out[col] = {"diterima": False, "invarian": res,
                        "alasan": f"Rumus “{g['rumus']}” hanya cocok {g['lolos']} dari {g['diuji']} baris "
                                  f"({g['persen']}%) dengan usulan ini."}
        else:
            out[col] = {"diterima": True, "invarian": res,
                        "alasan": "Lolos uji rumus: " + "; ".join(f"{r['rumus']} ({r['persen']}%)" for r in res)}
    return out


def ringkas(hasil: List[dict]) -> dict:
    """Ringkasan untuk layar: {status: lolos|gagal|tidak_diuji, kalimat}."""
    if not hasil:
        return {"status": "tidak_diuji", "kalimat": "Tidak ada rumus yang bisa diuji untuk berkas ini."}
    gagal = [r for r in hasil if not r["lulus"]]
    if gagal:
        g = gagal[0]
        return {"status": "gagal", "kalimat": f"Rumus “{g['rumus']}” hanya cocok di {g['lolos']} dari "
                                              f"{g['diuji']} baris — periksa kolom {', '.join(g['kolom_tersangka'][:3])}."}
    return {"status": "lolos", "kalimat": "Semua rumus uang cocok: " + "; ".join(
        f"{r['rumus']} ({r['lolos']}/{r['diuji']})" for r in hasil)}


def field_uang(st: SourceType, field: str) -> bool:
    f = st.field(field)
    return bool(f and f.kind in ("money", "pct", "num"))


def uji_berkas(st: SourceType, raw: bytes, filename: str, mapping: Optional[List[dict]] = None) -> dict:
    """Jalan pintas: baca berkas lewat mesin impor, petakan otomatis, jalankan rumus."""
    headers, rows = eng.parse_table(raw, filename, st)
    mapping = mapping or eng.auto_map(headers, st)
    rows, _ = eng.strip_description_rows(rows, mapping, st)
    hasil = uji(st, rows, mapping)
    return {"hasil": hasil, "ringkas": ringkas(hasil)}


__all__: List[str] = ["AMBANG_LOLOS", "RUMUS", "uji", "hakim_usulan", "ringkas", "uji_berkas",
                      "baris_kanonik", "field_uang", "rumus_untuk"]
