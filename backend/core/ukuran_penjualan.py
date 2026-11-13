"""core.ukuran_penjualan — SATU definisi omzet Marketing dan semua pembacanya.

KENAPA BERKAS INI ADA (audit AI 7 Nov 2026, §3.C; keputusan owner no. 7)
-----------------------------------------------------------------------
Sebelum berkas ini, "omzet" punya definisi berbeda di setiap layar:

* rekap harian menghitung pesanan BELUM DIBAYAR (status ``new``) sebagai omzet;
* dashboard memotong rekap di 500 baris (9 toko × 31 hari × 2 jenis sudah lebih);
* ringkasan pesanan menjumlah field ``revenue`` yang tidak dimiliki pesanan impor;
* fitur AI marketing memakai ``created_at`` (waktu impor) dan ``total_amount``
  (field yang tidak ada), sehingga omzet terbaca 0;
* produk terlaris menjumlah omzet SATU PESANAN untuk setiap barisnya.

Aturan baku (keputusan owner, dipakai layar, laporan, dan Asisten AI):

1. **Omzet** = ``metrics.revenue`` rekap harian (``marketing_sales_data``,
   ``revenue_type=total``) — omzet produk setelah diskon penjual, sebelum
   potongan platform (atau nilai pesanan bila toko memakai basis itu, K1).
   Rekap turunan dihitung dari pesanan dengan aturan nomor 2.
2. **Pesanan yang dihitung**: bukan ``cancelled`` dan bukan pesanan ``new`` yang
   belum dibayar (:func:`belum_dibayar`).
3. **Retur dilaporkan terpisah**: omzet tetap bruto; nilai retur dan "omzet
   setelah retur" disajikan berdampingan.
4. **Biaya platform hanya dari laporan dana dilepas** (``marketing_settlements``),
   dikelompokkan menurut ``settlement_date``.
5. **Data contoh tidak pernah dihitung**: dokumen ber-``_seed_origin`` dibuang.
6. **Tanggal pesanan** (``order_date``) menyimpan jam dinding WIB berlabel UTC.
   Pengelompokan memakai bagian tanggal APA ADANYA, tanpa digeser zona waktu —
   sama dengan yang dilihat staf di Seller Center.

Rincian per SKU/kanal/produk dibaca dari ``marketing_orders.items[]`` lewat
pembaca defensif ``core.marketing_daily_rollup`` (bentuk impor maupun manual).
Total SELALU dari rekap harian; rincian disertai cakupannya terhadap total.

Tidak ada fungsi di sini yang mengembalikan nama, nomor HP, atau alamat pembeli.
Pembeli hanya dihitung (jumlah unik), tidak pernah ditampilkan.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import marketing_daily_rollup as _rollup
from core import bulan_marketing as _bulan
from core import marketing_sales_shape as _shape

DAILY = "marketing_sales_data"
ORDERS = "marketing_orders"
ACCOUNTS = "marketing_platform_accounts"
TARGETS = "marketing_account_targets"
ADS = "marketing_ads_data"
LIVE = "marketing_live_sessions"
SETTLEMENTS = "marketing_settlements"
CATALOG_ITEMS = "marketing_catalog_items"

DEFINISI_OMZET = (
    "Omzet = penjualan produk setelah diskon penjual dan sebelum potongan platform "
    "(atau nilai pesanan bila toko memakai basis itu), diambil dari rekap harian. "
    "Pesanan batal dan pesanan belum dibayar tidak dihitung. Retur dilaporkan terpisah "
    "(omzet setelah retur = omzet - retur). Biaya platform hanya dari laporan dana "
    "dilepas menurut tanggal dana dilepas. Data contoh tidak dihitung.")

MAKS_HARI = 400               # rentang terpanjang satu permintaan analitik
TANPA_CONTOH = {"_seed_origin": {"$ne": True}}

# ══════════════════════════════════════════════════════════════════════════════
# 1. DEFINISI: PESANAN MANA YANG MENJADI OMZET
# ══════════════════════════════════════════════════════════════════════════════
STATUS_BATAL = ("cancelled", "canceled")
STATUS_BARU = "new"
# Istilah mentah platform/webhook yang berarti "sudah dibayar" walau status
# kanoniknya masih `new` (lihat `core.order_status.EXTERNAL_STATUS_MAP`).
STATUS_MENTAH_SUDAH_BAYAR = ("payment_verified", "paid", "PAYMENT_VERIFIED", "PAID")
SUMBER_MANUAL = "manual_input"
# Field yang WAJIB ikut diproyeksikan setiap pembaca pesanan supaya predikat
# di bawah bisa bekerja (proyeksi sempit = semua pesanan `new` dianggap belum bayar).
PROYEKSI_STATUS = {"status": 1, "paid_at": 1, "_source_type": 1, "status_assumed": 1,
                   "platform_status": 1, "_seed_origin": 1}


def _status(o: Optional[dict]) -> str:
    return str((o or {}).get("status") or "").strip().lower()


def data_contoh(doc: Optional[dict]) -> bool:
    """Dokumen data contoh (seeder demo) — tidak pernah dihitung."""
    return bool((doc or {}).get("_seed_origin"))


def belum_dibayar(o: Optional[dict]) -> bool:
    """Pesanan ``new`` yang BELUM dibayar pembeli.

    Status ``new`` pada ekspor marketplace berarti "Belum dibayar" (kamus status
    impor), jadi uangnya belum ada. Pengecualian yang tetap dihitung omzet:

    * ada ``paid_at`` (waktu dibayar tercatat);
    * pesanan manual yang diinput staf (``_source_type=manual_input``) — staf
      mencatat pesanan yang sudah disepakati, alurnya tidak punya langkah bayar;
    * impor lama tanpa kolom status (``status_assumed``) — statusnya tebakan
      sistem, bukan kata platform;
    * istilah mentah webhook ``payment_verified``.
    """
    if _status(o) != STATUS_BARU:
        return False
    o = o or {}
    if o.get("paid_at") not in (None, ""):
        return False
    if o.get("_source_type") == SUMBER_MANUAL:
        return False
    if o.get("status_assumed") is True:
        return False
    if str(o.get("platform_status") or "").strip() in STATUS_MENTAH_SUDAH_BAYAR:
        return False
    return True


def dihitung_omzet(o: Optional[dict]) -> bool:
    """Apakah satu pesanan ikut omzet: bukan contoh, bukan batal, bukan belum bayar."""
    return (not data_contoh(o)) and _status(o) not in STATUS_BATAL and not belum_dibayar(o)


def filter_dihitung_omzet() -> dict:
    """Saringan Mongo yang SETARA dengan :func:`dihitung_omzet` (untuk pipeline).

    Diuji setara dengan predikat Python di `tests/unit/test_asisten_ai_data.py`.
    """
    return {"$and": [
        dict(TANPA_CONTOH),
        {"status": {"$nin": list(STATUS_BATAL)}},
        {"$or": [
            {"status": {"$ne": STATUS_BARU}},
            {"paid_at": {"$nin": [None, ""]}},
            {"_source_type": SUMBER_MANUAL},
            {"status_assumed": True},
            {"platform_status": {"$in": list(STATUS_MENTAH_SUDAH_BAYAR)}},
        ]},
    ]}


# Ekspresi omzet PRODUK satu pesanan untuk pipeline (cadangan dokumen lama).
EKSPR_OMZET_PRODUK = {"$ifNull": ["$revenue_product", {"$ifNull": ["$revenue", "$total_payment"]}]}


# ══════════════════════════════════════════════════════════════════════════════
# 2. PERIODE & TANGGAL
# ══════════════════════════════════════════════════════════════════════════════
_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
          "September", "Oktober", "November", "Desember"]
_BULAN_PENDEK = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


class PeriodeSalah(ValueError):
    """Periode tidak sah — pesannya sudah berbahasa Indonesia untuk pengguna."""


def tanggal(value: Any, nama: str = "tanggal") -> str:
    """Isian → ``"YYYY-MM-DD"`` yang sah, atau :class:`PeriodeSalah`."""
    s = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise PeriodeSalah(f"Isian {nama} '{value}' bukan tanggal yang sah (format TTTT-BB-HH).") from None


def periode(dari: Any, sampai: Any, *, hari_ini: Optional[date] = None,
            maks_hari: int = MAKS_HARI) -> Tuple[str, str]:
    """Rentang yang sah. Kosong → awal bulan berjalan s.d. hari ini (WIB)."""
    if not dari and not sampai:
        today = hari_ini or _today_wib()
        return today.replace(day=1).isoformat(), today.isoformat()
    d0 = tanggal(dari or sampai, "dari")
    d1 = tanggal(sampai or dari, "sampai")
    if d1 < d0:
        raise PeriodeSalah("Tanggal 'sampai' lebih awal daripada tanggal 'dari'.")
    if jumlah_hari(d0, d1) > maks_hari:
        raise PeriodeSalah(f"Rentang paling panjang {maks_hari} hari. Persempit periodenya.")
    return d0, d1


def _today_wib() -> date:
    from utils.waktu import today_wib
    return today_wib()


def jumlah_hari(dari: str, sampai: str) -> int:
    return (date.fromisoformat(sampai) - date.fromisoformat(dari)).days + 1


def _geser_tahun(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                       # 29 Februari → 28 Februari
        return d.replace(year=d.year + n, day=28)


def periode_pembanding(dari: str, sampai: str, mode: Optional[str]) -> Optional[Tuple[str, str]]:
    """``periode_sebelumnya`` = rentang sama panjang tepat sebelumnya;
    ``tahun_lalu`` = tanggal yang sama setahun lalu; ``tidak``/kosong = None."""
    mode = (mode or "tidak").strip().lower()
    if mode in ("", "tidak", "none"):
        return None
    d0, d1 = date.fromisoformat(dari), date.fromisoformat(sampai)
    if mode == "periode_sebelumnya":
        n = (d1 - d0).days + 1
        return (d0 - timedelta(days=n)).isoformat(), (d0 - timedelta(days=1)).isoformat()
    if mode == "tahun_lalu":
        return _geser_tahun(d0, -1).isoformat(), _geser_tahun(d1, -1).isoformat()
    raise PeriodeSalah("Pilihan pembanding harus periode_sebelumnya, tahun_lalu, atau tidak.")


def kunci_tanggal(value: Any) -> Optional[str]:
    """Tanggal tersimpan (datetime ATAU string) → ``YYYY-MM-DD`` tanpa geser zona."""
    return _rollup.order_date_key(value)


def filter_tanggal(field: str, dari: str, sampai: str) -> dict:
    """Saringan rentang yang tahan DUA bentuk simpanan (datetime dan string)."""
    t0 = datetime.fromisoformat(dari).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(sampai).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return {"$or": [
        {field: {"$gte": t0, "$lt": t1}},
        {field: {"$gte": dari, "$lte": sampai + "￿"}},
    ]}


def label_bulan(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{_BULAN[m - 1]} {y}"


def kunci_minggu(d: str) -> str:
    """Minggu Senin–Minggu (kesepakatan laporan rapat) → ``YYYY-Www`` ISO."""
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def label_minggu(kunci: str) -> str:
    y, w = int(kunci[:4]), int(kunci[6:])
    senin = date.fromisocalendar(y, w, 1)
    minggu = senin + timedelta(days=6)
    return (f"{senin.day} {_BULAN_PENDEK[senin.month - 1]} – "
            f"{minggu.day} {_BULAN_PENDEK[minggu.month - 1]} {minggu.year}")


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _rp(v: float) -> float:
    return float(round(v or 0))


def _pct(a: float, b: float, nd: int = 1) -> Optional[float]:
    return round(a / b * 100, nd) if b else None


def capaian_gabungan(baris: Iterable[Any], target_of, aktual_of, nd: int = 1) -> dict:
    """Persen capaian GABUNGAN dengan pembilang & penyebut dari himpunan toko yang SAMA.

    M-04 (audit Marketing 9 Nov 2026) — laporan bulanan, target, rapat mingguan, dan analitik
    dulu membagi omzet SEMUA toko dengan target toko yang PUNYA target: satu toko bertarget
    68,6% tampil sebagai 117,3% (mingguan 1.115,9%). Sekarang hanya toko bertarget yang
    dibandingkan; omzet toko tanpa target dilaporkan terpisah (`aktual_tanpa_target`).
    """
    tgt = akt = tanpa = 0.0
    n_t = n_0 = 0
    for b in baris or []:
        t = _num(target_of(b))
        a = _num(aktual_of(b))
        if t > 0:
            tgt += t
            akt += a
            n_t += 1
        else:
            tanpa += a
            n_0 += 1
    return {"target": tgt, "aktual_bertarget": akt, "aktual_tanpa_target": tanpa,
            "toko_bertarget": n_t, "toko_tanpa_target": n_0,
            "persen": round(akt / tgt * 100, nd) if tgt > 0 else None}


# ══════════════════════════════════════════════════════════════════════════════
# 3. TOKO YANG BOLEH DIBACA (lingkup toko + pilihan CV)
# ══════════════════════════════════════════════════════════════════════════════
PROYEKSI_TOKO = {"_id": 0, "id": 1, "account_name": 1, "account_code": 1, "platform": 1,
                 "status": 1, "revenue_basis": 1, "entity": 1}


async def toko_terlihat(db, user: Optional[dict], *, cv: Optional[str] = None,
                        toko_id: Optional[str] = None,
                        hanya_aktif: bool = False) -> List[dict]:
    """Toko yang boleh dibaca pemakai ini, dipotong CV dan (bila diminta) satu toko.

    Lingkup toko lewat SATU pintu `core.marketing_account_scope.visible_accounts`.
    Toko online milik CV Dewi Aditya: toko tanpa field ``entity`` = DA (aturan
    `core.entities.entity_match`), jadi CV Sukma hanya melihat toko yang memang
    ditandai SMU. ``toko_id`` di luar lingkup → 403 (pesan dari helper lingkup).
    """
    from core import entities as _ent
    from core import marketing_account_scope as _scope
    base: Dict[str, Any] = dict(_ent.entity_match(cv)) if cv else {}
    if hanya_aktif:
        base["status"] = "active"
    if toko_id:
        await _scope.assert_account_visible(db, user, toko_id)
        base["id"] = toko_id
    rows = await _scope.visible_accounts(db, user, base=base, projection=dict(PROYEKSI_TOKO),
                                         sort=[("account_code", 1)], limit=1000)
    return [r for r in rows if r.get("id")]


# ══════════════════════════════════════════════════════════════════════════════
# 4. PEMBACA TOTAL: REKAP HARIAN
# ══════════════════════════════════════════════════════════════════════════════
def baris_rekap(doc: dict) -> dict:
    """Satu dokumen rekap harian → angka baku (pembacaan lewat pembaca kanonik)."""
    m = _shape.read_metrics(doc)
    f = _shape.read_group(doc, "fulfillment")
    basis = doc.get("revenue_basis") or _shape.DEFAULT_BASIS
    if basis == _shape.BASIS_ORDER_AMOUNT:
        retur = _num(f.get("returned_value"))
    else:
        retur = (_num(f.get("returned_revenue_product")) if f.get("returned_revenue_product") is not None
                 else _num(f.get("returned_value")))
    traffic = _shape.read_group(doc, "traffic")
    return {
        "account_id": doc.get("account_id"),
        "date": _shape.norm_date(doc.get("date")),
        "omzet": _num(m.get("revenue")),
        "omzet_produk": _num(m.get("revenue_product")),
        "nilai_pesanan": _num(m.get("revenue_order_amount")),
        "diskon_penjual": _num(m.get("seller_discount")),
        "pesanan": _int(m.get("orders")),
        "unit": _int(m.get("units")),
        "pembeli": _int(m.get("buyers")),
        "retur_nilai": retur,
        "retur_pesanan": _int(f.get("returned_orders")),
        "batal_pesanan": _int(f.get("cancelled_orders")),
        "batal_nilai": _num(f.get("cancelled_value")),
        "belum_bayar_pesanan": _int(f.get("unpaid_orders")),
        "kanal": {k: _num(v) for k, v in (traffic or {}).items()},
        "sumber": doc.get("source") or "",
        "basis": basis,
        "_updated": doc.get("updated_at"),
    }


async def baca_rekap(db, account_ids: Sequence[str], dari: str, sampai: str,
                     revenue_type: str = "total") -> Tuple[List[dict], int]:
    """Semua rekap harian toko-toko ini dalam rentang — TANPA batas baris.

    → ``(baris, duplikat_diabaikan)``. Satu (toko, tanggal, jenis) hanya boleh
    satu dokumen; kalau DB lama masih punya kembaran (indeks unik belum
    terpasang), yang terbaru dipakai dan sisanya dihitung supaya terlihat.
    """
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return [], 0
    q = {"account_id": {"$in": ids}, "revenue_type": revenue_type,
         "date": {"$gte": dari, "$lte": sampai}, **TANPA_CONTOH}
    pilih: Dict[Tuple[str, str], dict] = {}
    dup = 0
    async for d in db[DAILY].find(q, {"_id": 0}):
        r = baris_rekap(d)
        key = (r["account_id"], r["date"])
        if key in pilih:
            dup += 1
            if str(r.get("_updated") or "") <= str(pilih[key].get("_updated") or ""):
                continue
        pilih[key] = r
    rows = sorted(pilih.values(), key=lambda r: (r["date"], r["account_id"]))
    for r in rows:
        r.pop("_updated", None)
    return rows, dup


_TOTAL_KEYS = ("omzet", "omzet_produk", "nilai_pesanan", "diskon_penjual", "pesanan", "unit",
               "pembeli", "retur_nilai", "retur_pesanan", "batal_pesanan", "batal_nilai",
               "belum_bayar_pesanan")


def jumlahkan(rows: Iterable[dict]) -> dict:
    """Total baku dari baris rekap: omzet, pesanan, unit, AOV, retur, batal."""
    t = {k: 0.0 for k in _TOTAL_KEYS}
    tanggal_ada = set()
    for r in rows:
        for k in _TOTAL_KEYS:
            t[k] += _num(r.get(k))
        tanggal_ada.add(r.get("date"))
    out = {k: (_rp(v) if k in ("omzet", "omzet_produk", "nilai_pesanan", "diskon_penjual",
                               "retur_nilai", "batal_nilai") else int(v)) for k, v in t.items()}
    out["aov"] = _rp(t["omzet"] / t["pesanan"]) if t["pesanan"] else 0.0
    out["omzet_setelah_retur"] = _rp(t["omzet"] - t["retur_nilai"])
    out["hari_ada_data"] = len(tanggal_ada - {None})
    return out


async def ringkas_omzet(db, accounts: Sequence[dict], dari: str, sampai: str) -> dict:
    """Total + per toko untuk daftar toko (dokumen toko) dalam rentang.

    Dipakai dashboard, performa, laporan bulanan, target, dan analitik AI supaya
    SEMUA layar menyebut angka yang sama untuk toko & periode yang sama.
    """
    ids = [a["id"] for a in accounts if a.get("id")]
    rows, dup = await baca_rekap(db, ids, dari, sampai)
    per: Dict[str, List[dict]] = {}
    for r in rows:
        per.setdefault(r["account_id"], []).append(r)
    return {"total": jumlahkan(rows),
            "per_toko": {aid: jumlahkan(per.get(aid, [])) for aid in ids},
            "baris": rows, "duplikat_diabaikan": dup}


# ══════════════════════════════════════════════════════════════════════════════
# 5. PEMBACA RINCIAN: PESANAN & ITEM (SKU / kanal / produk)
# ══════════════════════════════════════════════════════════════════════════════
PROYEKSI_PESANAN = {
    "_id": 0, "id": 1, "account_id": 1, "platform": 1, "order_date": 1, "order_channel": 1,
    "revenue_product": 1, "revenue": 1, "total_payment": 1, "price_final": 1, "quantity": 1,
    "catalog_item_id": 1, "fg_material_id": 1, "sku_id": 1, "product_name": 1, "variation": 1,
    "buyer_username": 1, "customer_phone": 1, "customer_name": 1, "items": 1,
    # 11 Nov 2026 — atribusi kreator (kolom "Creator Handle" TikTok / "Akun kreator" manual)
    "creator_handle": 1, "creator_id": 1, "creator_name": 1,
    **PROYEKSI_STATUS,
}


async def baca_pesanan(db, account_ids: Sequence[str], dari: str, sampai: str) -> List[dict]:
    """Pesanan yang DIHITUNG omzet (aturan baku) dalam rentang tanggal pesanan."""
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return []
    q = {"$and": [{"account_id": {"$in": ids}}, filter_tanggal("order_date", dari, sampai),
                  dict(TANPA_CONTOH)]}
    out: List[dict] = []
    async for o in db[ORDERS].find(q, PROYEKSI_PESANAN):
        k = kunci_tanggal(o.get("order_date"))
        if k is None or not (dari <= k <= sampai) or not dihitung_omzet(o):
            continue
        o["_tanggal"] = k
        out.append(o)
    return out


def kunci_pembeli(o: dict) -> str:
    """Kunci hitung pembeli unik (TIDAK pernah dikeluarkan dari modul ini)."""
    return str(o.get("buyer_username") or o.get("customer_phone")
               or o.get("customer_name") or "").strip().lower()


def baris_item(o: dict) -> List[dict]:
    """Baris SKU satu pesanan, omzet & unit per baris (bukan omzet pesanan per baris).

    Pesanan lama tanpa ``items[]`` (impor format lama) dibaca sebagai satu baris
    dari akar dokumen. Inilah perbaikan "produk terlaris dihitung dobel": dulu
    baris tanpa ``sku_subtotal_after_discount`` jatuh ke omzet SELURUH pesanan.
    """
    items = o.get("items") or []
    if not items:
        return [{"catalog_item_id": o.get("catalog_item_id"),
                 "fg_material_id": o.get("fg_material_id"), "model_id": None,
                 "sku": o.get("sku_id") or "", "nama": o.get("product_name") or "",
                 "unit": _int(o.get("quantity")) or 1,
                 "omzet": _rollup.order_revenue_product(o), "hpp_snapshot": 0.0}]
    out = []
    for it in items:
        out.append({
            "catalog_item_id": it.get("catalog_item_id"),
            "fg_material_id": it.get("fg_material_id"),
            "model_id": it.get("model_id"),
            "sku": (it.get("seller_sku") or it.get("variant_sku") or it.get("sku_code")
                    or it.get("platform_sku_id") or ""),
            "nama": it.get("product_name_raw") or it.get("product_name") or "",
            "unit": _rollup.item_qty(it),
            "omzet": _rollup.item_revenue(it),
            "hpp_snapshot": _num(it.get("hpp_snapshot")),
        })
    return out


def _norm(s: Any) -> str:
    from core import marketing_account_scope as _scope
    return _scope.norm(s)


async def katalog_untuk(db, ids: Iterable[str]) -> Dict[str, dict]:
    """Item katalog (nama, sku, model, HPP) untuk id yang muncul di pesanan."""
    ids = sorted({i for i in ids if i})
    out: Dict[str, dict] = {}
    for n in range(0, len(ids), 500):
        async for d in db[CATALOG_ITEMS].find(
                {"id": {"$in": ids[n:n + 500]}},
                {"_id": 0, "id": 1, "name": 1, "sku": 1, "model_id": 1, "fg_material_id": 1,
                 "hpp": 1, "fg_color": 1}):
            out[d["id"]] = d
    return out


TRAFFIC_LABEL = {
    "live": "Live", "video": "Video", "product_card": "Kartu produk", "ads": "Iklan",
    "affiliate": "Afiliasi", "campaign": "Kampanye", "search": "Pencarian",
    "organic": "Organik", "other": "Lainnya",
}


def kanal_pesanan(o: dict) -> str:
    ch = str(o.get("order_channel") or "other").strip().lower()
    return ch if ch in TRAFFIC_LABEL else "other"


def kreator_pesanan(o: dict) -> str:
    """11 Nov 2026 — akun kreator yang tercatat di pesanan ("" = bukan lewat kreator).

    TikTok menulis kanal (LIVE/Video/Kartu produk) dan kreator di DUA kolom terpisah, jadi
    "lewat kreator" adalah lapisan di ATAS kanal — bagian dari omzet kanalnya, bukan kanal
    tambahan (dijumlah ke kanal = dihitung dua kali).
    """
    return str(o.get("creator_handle") or o.get("creator_name") or o.get("creator_id") or "").strip()


def kunci_item(line: dict, kat: Dict[str, dict], cara: str) -> Tuple[str, str, str]:
    """→ (kunci, label, sku) untuk ``cara`` ∈ katalog | produk | sku."""
    cid = line.get("catalog_item_id")
    k = kat.get(cid or "") or {}
    sku = k.get("sku") or line.get("sku") or ""
    nama = k.get("name") or line.get("nama") or sku or "Tanpa nama"
    if cara == "produk":                       # model (semua warna/ukuran & toko)
        if k.get("model_id") or line.get("model_id"):
            return f"model:{k.get('model_id') or line.get('model_id')}", nama, ""
        return f"nama:{_norm(nama)}", nama, ""
    if cara == "sku":                          # SKU barang jadi lintas toko
        fg = k.get("fg_material_id") or line.get("fg_material_id")
        label = f"{nama} ({sku})" if sku and sku != nama else nama
        if fg:
            return f"fg:{fg}", label, sku
        if sku:
            return f"sku:{_norm(sku)}", label, sku
        return f"nama:{_norm(nama)}", label, sku
    # cara == "katalog": item katalog per toko (perbaikan produk terlaris, audit #2)
    if cid:
        return f"item:{cid}", nama, sku
    if sku:
        return f"sku:{_norm(sku)}", nama, sku
    return f"nama:{_norm(nama)}", nama, sku


async def rincian_item(db, orders: Sequence[dict], cara: str) -> List[dict]:
    """Agregat per item/produk/SKU: unit, omzet, pesanan, HPP & laba kotor bila ada."""
    lines_per_order = [(o, baris_item(o)) for o in orders]
    kat = await katalog_untuk(db, (ln.get("catalog_item_id")
                                   for _o, lines in lines_per_order for ln in lines))
    acc: Dict[str, dict] = {}
    for o, lines in lines_per_order:
        for ln in lines:
            key, label, sku = kunci_item(ln, kat, cara)
            b = acc.setdefault(key, {"kunci": key, "label": label, "sku": sku, "unit": 0,
                                     "omzet": 0.0, "_pesanan": set(), "unit_ber_hpp": 0,
                                     "omzet_ber_hpp": 0.0, "hpp": 0.0, "_toko": set()})
            b["unit"] += ln["unit"]
            b["omzet"] += ln["omzet"]
            b["_pesanan"].add(o.get("id") or id(o))
            b["_toko"].add(o.get("account_id"))
            hpp_unit = ln.get("hpp_snapshot") or _num((kat.get(ln.get("catalog_item_id") or "") or {}).get("hpp"))
            if hpp_unit > 0:
                b["unit_ber_hpp"] += ln["unit"]
                b["omzet_ber_hpp"] += ln["omzet"]
                b["hpp"] += hpp_unit * ln["unit"]
    out = []
    for b in acc.values():
        laba = b["omzet_ber_hpp"] - b["hpp"]
        out.append({
            "kunci": b["kunci"], "label": b["label"], "sku": b["sku"],
            "unit": b["unit"], "omzet": _rp(b["omzet"]), "pesanan": len(b["_pesanan"]),
            "toko": len(b["_toko"]),
            "hpp": _rp(b["hpp"]) if b["unit_ber_hpp"] else None,
            "laba_kotor": _rp(laba) if b["unit_ber_hpp"] else None,
            "margin_persen": _pct(laba, b["omzet_ber_hpp"]) if b["omzet_ber_hpp"] > 0 else None,
            "hpp_cakupan_persen": _pct(b["unit_ber_hpp"], b["unit"]) if b["unit"] else 0.0,
            "_unit_ber_hpp": b["unit_ber_hpp"], "_omzet_ber_hpp": b["omzet_ber_hpp"],
            "_hpp": b["hpp"],
        })
    out.sort(key=lambda r: (-r["omzet"], r["label"]))
    return out


def rincian_kanal(orders: Sequence[dict], rows: Optional[Sequence[dict]] = None) -> List[dict]:
    """Omzet, pesanan, unit, dan pembeli per kanal.

    11 Nov 2026 (rincian kanal manual) — bila ``rows`` (baris :func:`baca_rekap`) diberikan,
    OMZET per kanal dibaca dari pecahan kanal rekap harian (``kanal`` = kanal pesanan +
    rincian yang diketik staf, lihat ``core.marketing_sales_shape.merge_traffic``) untuk
    setiap (toko, tanggal) yang punya pecahan; tanggal tanpa pecahan memakai pesanannya.
    Tanpa ini, omzet yang diinput manual per kanal tidak pernah muncul di laporan.
    Jumlah pesanan/unit/pembeli selalu dari pesanan (rekap tidak menyimpannya per kanal).
    ``lewat_kreator``/``pesanan_kreator`` = bagian kanal itu yang pesanannya mencatat akun
    kreator (:func:`kreator_pesanan`) — BAGIAN dari omzet kanal, tidak dijumlah ke total.
    """
    acc: Dict[str, dict] = {}

    def bucket(k: str) -> dict:
        return acc.setdefault(k, {"kunci": k, "label": TRAFFIC_LABEL[k], "omzet": 0.0,
                                  "pesanan": 0, "unit": 0, "_pembeli": set(),
                                  "lewat_kreator": 0.0, "pesanan_kreator": 0})

    hari_berkanal = set()
    for r in rows or ():
        kanal = {k: _num(v) for k, v in (r.get("kanal") or {}).items() if k in TRAFFIC_LABEL}
        if not any(kanal.values()):
            continue
        hari_berkanal.add((r.get("account_id"), r.get("date")))
        for k, v in kanal.items():
            if v:
                bucket(k)["omzet"] += v
    for o in orders:
        k = kanal_pesanan(o)
        b = bucket(k)
        hari = (o.get("account_id"), o.get("_tanggal") or kunci_tanggal(o.get("order_date")))
        if hari not in hari_berkanal:
            b["omzet"] += _rollup.order_revenue_product(o)
        b["pesanan"] += 1
        b["unit"] += sum(ln["unit"] for ln in baris_item(o))
        pk = kunci_pembeli(o)
        if pk:
            b["_pembeli"].add(pk)
        if kreator_pesanan(o):
            b["lewat_kreator"] += _rollup.order_revenue_product(o)
            b["pesanan_kreator"] += 1
    out = [{"kunci": b["kunci"], "label": b["label"], "omzet": _rp(b["omzet"]),
            "pesanan": b["pesanan"], "unit": b["unit"], "pembeli": len(b["_pembeli"]),
            "lewat_kreator": _rp(b["lewat_kreator"]), "pesanan_kreator": b["pesanan_kreator"]}
           for b in acc.values()]
    out.sort(key=lambda r: -r["omzet"])
    return out


def ringkas_kreator(orders: Sequence[dict]) -> dict:
    """11 Nov 2026 — omzet yang tercatat LEWAT KREATOR (afiliasi) pada pesanan yang dihitung.

    → ``{omzet, pesanan, kreator, kreator_belum_terdaftar}``. Hanya JUMLAH yang keluar
    (tidak ada nama/akun kreator maupun data pembeli). ``kreator_belum_terdaftar`` = akun
    kreator di pesanan yang belum tertaut ke master KOL & Kreator — omzetnya tetap terhitung
    di sini, tetapi belum muncul di laporan per kreator.
    """
    omzet = 0.0
    pesanan = 0
    akun: set = set()
    belum: set = set()
    for o in orders:
        h = kreator_pesanan(o)
        if not h:
            continue
        omzet += _rollup.order_revenue_product(o)
        pesanan += 1
        k = _norm(h)
        akun.add(k)
        if not o.get("creator_id"):
            belum.add(k)
    return {"omzet": _rp(omzet), "pesanan": pesanan, "kreator": len(akun),
            "kreator_belum_terdaftar": len(belum)}


KANAL_UTAMA = ("live", "video", "product_card", "affiliate")


def kanal_per_toko(rows: Sequence[dict], orders: Sequence[dict],
                   toko: Dict[str, dict]) -> List[dict]:
    """11 Nov 2026 — pecahan omzet per kanal untuk SETIAP toko dalam periode.

    → ``[{account_id, account_name, platform, omzet, kanal{kode: omzet}, belum_dirinci,
    lewat_kreator}]``.
    ``belum_dirinci`` = omzet rekap yang tidak punya pecahan kanal (hari tanpa pesanan
    berkanal dan tanpa rincian ketikan) — ditampilkan apa adanya, tidak ditebak.
    """
    per_rows: Dict[str, List[dict]] = {}
    for r in rows:
        per_rows.setdefault(r.get("account_id"), []).append(r)
    per_orders: Dict[str, List[dict]] = {}
    for o in orders:
        per_orders.setdefault(o.get("account_id"), []).append(o)
    out: List[dict] = []
    for aid in sorted(set(per_rows) | set(per_orders), key=lambda a: str(a)):
        rs = per_rows.get(aid, [])
        omzet = jumlahkan(rs)["omzet"]
        kanal = {k: 0.0 for k in TRAFFIC_LABEL}
        lewat_kreator = 0.0
        for c in rincian_kanal(per_orders.get(aid, []), rs):
            kanal[c["kunci"]] = c["omzet"]
            lewat_kreator += c["lewat_kreator"]
        terinci = sum(kanal.values())
        a = toko.get(aid) or {}
        out.append({"account_id": aid, "account_name": a.get("account_name") or aid,
                    "platform": _platform(a.get("platform")), "omzet": _rp(omzet),
                    "kanal": {k: _rp(v) for k, v in kanal.items()},
                    "belum_dirinci": _rp(max(0.0, omzet - terinci)),
                    # bagian omzet toko yang pesanannya mencatat akun kreator (bukan tambahan)
                    "lewat_kreator": _rp(lewat_kreator)})
    out.sort(key=lambda r: (-r["omzet"], r["account_name"]))
    return out


def pembeli_unik(orders: Iterable[dict], kunci_grup=None) -> Dict[Any, int]:
    """Jumlah pembeli unik per grup (``kunci_grup(o)``) atau total (kunci None)."""
    sets: Dict[Any, set] = {}
    for o in orders:
        pk = kunci_pembeli(o)
        if not pk:
            continue
        g = kunci_grup(o) if kunci_grup else None
        sets.setdefault(g, set()).add(pk)
    return {g: len(s) for g, s in sets.items()}


# ══════════════════════════════════════════════════════════════════════════════
# 6. ANALITIK PENJUALAN (dipakai /api/marketing/analitik/penjualan)
# ══════════════════════════════════════════════════════════════════════════════
KELOMPOK_PENJUALAN = ("toko", "platform", "kanal", "produk", "sku", "hari", "minggu", "bulan")
KELOMPOK_WAKTU = ("hari", "minggu", "bulan")
KELOMPOK_PESANAN = ("kanal", "produk", "sku")


def _platform(p: Any) -> str:
    from core import marketing_account_scope as _scope
    return _scope.platform_family(p) or "lainnya"


def _kunci_waktu(d: str, kelompok: str) -> Tuple[str, str]:
    if kelompok == "hari":
        dd = date.fromisoformat(d)
        return d, f"{dd.day} {_BULAN_PENDEK[dd.month - 1]} {dd.year}"
    if kelompok == "minggu":
        k = kunci_minggu(d)
        return k, label_minggu(k)
    return d[:7], label_bulan(d[:7])


def _grup_rekap(rows: Sequence[dict], orders: Sequence[dict], toko: Dict[str, dict],
                kelompok: str) -> List[dict]:
    """Kelompok berbasis rekap (toko/platform/hari/minggu/bulan) + pembeli unik dari pesanan."""
    def key_of(account_id: str, d: str) -> Tuple[str, str]:
        if kelompok == "toko":
            a = toko.get(account_id) or {}
            return account_id, a.get("account_name") or account_id
        if kelompok == "platform":
            p = _platform((toko.get(account_id) or {}).get("platform"))
            return p, p.capitalize()
        return _kunci_waktu(d, kelompok)

    grp: Dict[str, List[dict]] = {}
    labels: Dict[str, str] = {}
    for r in rows:
        k, lab = key_of(r["account_id"], r["date"])
        grp.setdefault(k, []).append(r)
        labels[k] = lab
    buyers = pembeli_unik(orders, lambda o: key_of(o.get("account_id"), o["_tanggal"])[0])
    out = []
    for k, rs in grp.items():
        t = jumlahkan(rs)
        out.append({"kunci": k, "label": labels[k], "omzet": t["omzet"], "pesanan": t["pesanan"],
                    "unit": t["unit"], "pembeli": buyers.get(k, 0), "aov": t["aov"],
                    "retur_nilai": t["retur_nilai"], "batal_pesanan": t["batal_pesanan"],
                    "omzet_setelah_retur": t["omzet_setelah_retur"]})
    if kelompok in KELOMPOK_WAKTU:
        out.sort(key=lambda r: r["kunci"])
    else:
        out.sort(key=lambda r: (-r["omzet"], r["label"]))
    return out


async def _grup(db, rows, orders, toko, kelompok) -> List[dict]:
    if kelompok in KELOMPOK_PESANAN:
        if kelompok == "kanal":
            return rincian_kanal(orders, rows)
        rinci = await rincian_item(db, orders, kelompok)
        return [{"kunci": r["kunci"], "label": r["label"], "sku": r["sku"], "omzet": r["omzet"],
                 "pesanan": r["pesanan"], "unit": r["unit"],
                 "aov": _rp(r["omzet"] / r["pesanan"]) if r["pesanan"] else 0.0}
                for r in rinci]
    return _grup_rekap(rows, orders, toko, kelompok)


def _selisih(a: float, b: float) -> dict:
    return {"nilai": _rp(a - b) if isinstance(a, float) or isinstance(b, float) else a - b,
            "persen": _pct(a - b, b)}


async def analitik_penjualan(db, accounts: Sequence[dict], dari: str, sampai: str, *,
                             kelompok: str = "toko", bandingkan: Optional[str] = None,
                             limit: Optional[int] = None) -> dict:
    """Total baku + kelompok + pembanding untuk toko-toko ``accounts``."""
    kelompok = (kelompok or "toko").strip().lower()
    if kelompok not in KELOMPOK_PENJUALAN:
        raise PeriodeSalah("Pilihan kelompok harus salah satu dari: " + ", ".join(KELOMPOK_PENJUALAN) + ".")
    toko = {a["id"]: a for a in accounts}
    ids = list(toko)
    rows, dup = await baca_rekap(db, ids, dari, sampai)
    orders = await baca_pesanan(db, ids, dari, sampai)
    total = jumlahkan(rows)
    total["pembeli"] = pembeli_unik(orders).get(None, 0) if orders else total["pembeli"]
    grup = await _grup(db, rows, orders, toko, kelompok)

    catatan: List[str] = []
    pemb = None
    pr = periode_pembanding(dari, sampai, bandingkan)
    if pr:
        rows2, _d2 = await baca_rekap(db, ids, pr[0], pr[1])
        orders2 = await baca_pesanan(db, ids, pr[0], pr[1])
        total2 = jumlahkan(rows2)
        total2["pembeli"] = pembeli_unik(orders2).get(None, 0) if orders2 else total2["pembeli"]
        grup2 = await _grup(db, rows2, orders2, toko, kelompok)
        pemb = {"mode": bandingkan, "periode": {"dari": pr[0], "sampai": pr[1]},
                "total": total2,
                "selisih": {k: _selisih(total[k], total2[k])
                            for k in ("omzet", "pesanan", "unit", "aov", "retur_nilai")}}
        if kelompok in KELOMPOK_WAKTU:
            # deret waktu dibandingkan menurut URUTAN (hari ke-1 vs hari ke-1)
            for i, r in enumerate(grup):
                if i < len(grup2):
                    r["pembanding"] = {"label": grup2[i]["label"], "omzet": grup2[i]["omzet"],
                                       "pesanan": grup2[i]["pesanan"]}
                    r["selisih_omzet_persen"] = _pct(r["omzet"] - grup2[i]["omzet"], grup2[i]["omzet"])
        else:
            by = {g["kunci"]: g for g in grup2}
            for r in grup:
                p = by.get(r["kunci"])
                r["pembanding"] = {"omzet": p["omzet"], "pesanan": p["pesanan"]} if p else {"omzet": 0.0, "pesanan": 0}
                r["selisih_omzet_persen"] = _pct(r["omzet"] - r["pembanding"]["omzet"], r["pembanding"]["omzet"])

    for r in grup:
        r["porsi_persen"] = _pct(r["omzet"], total["omzet"]) if kelompok not in KELOMPOK_WAKTU else None

    batas = limit or (MAKS_HARI if kelompok in KELOMPOK_WAKTU else 20)
    dipotong = len(grup) > batas
    lainnya = None
    if dipotong:
        sisa = grup[batas:]
        grup = grup[:batas]
        if kelompok not in KELOMPOK_WAKTU:
            lainnya = {"jumlah_kelompok": len(sisa), "omzet": _rp(sum(r["omzet"] for r in sisa)),
                       "pesanan": sum(r["pesanan"] for r in sisa)}

    cakupan = None
    if kelompok in KELOMPOK_PESANAN:
        rinci_omzet = sum(r["omzet"] for r in grup) + (lainnya["omzet"] if lainnya else 0.0)
        cakupan = {"omzet_rincian": _rp(rinci_omzet),
                   "persen_dari_total": _pct(rinci_omzet, total["omzet"]),
                   "pesanan_terbaca": len(orders),
                   "catatan": (("Omzet per kanal dibaca dari pecahan kanal rekap harian (kanal pesanan "
                                "ditambah rincian kanal yang diisi staf); hari tanpa pecahan memakai "
                                "pesanannya. Jumlah pesanan per kanal hanya dari pesanan.")
                               if kelompok == "kanal" else
                               ("Rincian dibaca dari pesanan impor/manual (omzet produk per baris SKU). "
                                "Toko yang hanya mengisi rekap harian tanpa pesanan tidak punya rincian."))}
        if total["omzet"] and abs(rinci_omzet - total["omzet"]) > max(1000.0, total["omzet"] * 0.01):
            catatan.append("Jumlah rincian tidak sama dengan total omzet: sebagian omzet berasal dari "
                           "rekap harian tanpa pesanan, atau toko memakai basis nilai pesanan.")
    if dup:
        catatan.append(f"{dup} rekap harian kembar diabaikan (dipakai yang terbaru).")
    if total["belum_bayar_pesanan"]:
        catatan.append(f"{total['belum_bayar_pesanan']} pesanan belum dibayar tidak dihitung sebagai omzet.")
    nonaktif = [a.get("account_name") for a in accounts if (a.get("status") or "active") != "active"]
    if nonaktif:
        catatan.append("Termasuk toko nonaktif: " + ", ".join(sorted(n for n in nonaktif if n)) + ".")

    return {
        "periode": {"dari": dari, "sampai": sampai, "hari": jumlah_hari(dari, sampai)},
        "definisi": DEFINISI_OMZET,
        "satuan": {"uang": "Rp", "unit": "pcs"},
        "toko": {"jumlah": len(accounts),
                 "daftar": [{"id": a["id"], "nama": a.get("account_name"),
                             "platform": _platform(a.get("platform"))} for a in accounts][:50]},
        "total": total,
        "pembanding": pemb,
        "kelompok": {"jenis": kelompok, "baris": grup, "jumlah_baris": len(grup),
                     "dipotong": dipotong, "lainnya": lainnya},
        "cakupan_rincian": cakupan,
        "catatan": catatan,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. PRODUK: TERLARIS / TERBAWAH + MARJIN DARI HPP SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════
async def analitik_produk(db, accounts: Sequence[dict], dari: str, sampai: str, *,
                          urut: str = "teratas", cara: str = "produk",
                          limit: int = 10) -> dict:
    """Produk teratas/terbawah menurut omzet, dengan marjin kotor bila HPP ada.

    HPP per unit = ``items[].hpp_snapshot`` (dibekukan saat pesanan masuk),
    cadangan HPP katalog hari ini. Cakupan HPP = unit ber-HPP ÷ seluruh unit.
    """
    if cara not in ("produk", "sku", "katalog"):
        raise PeriodeSalah("Pilihan cara harus produk, sku, atau katalog.")
    ids = [a["id"] for a in accounts]
    orders = await baca_pesanan(db, ids, dari, sampai)
    rows = await rincian_item(db, orders, cara)
    unit = sum(r["unit"] for r in rows)
    unit_cov = sum(r["_unit_ber_hpp"] for r in rows)
    omzet = sum(r["omzet"] for r in rows)
    omzet_cov = sum(r["_omzet_ber_hpp"] for r in rows)
    hpp = sum(r["_hpp"] for r in rows)
    if (urut or "teratas") == "terbawah":
        rows = sorted(rows, key=lambda r: (r["omzet"], r["label"]))
    for r in rows:
        for k in ("_unit_ber_hpp", "_omzet_ber_hpp", "_hpp"):
            r.pop(k, None)
    n = max(1, min(int(limit or 10), 100))
    return {
        "periode": {"dari": dari, "sampai": sampai},
        "definisi": DEFINISI_OMZET,
        "urut": "terbawah" if urut == "terbawah" else "teratas",
        "cara": cara,
        "total": {"produk": len(rows), "unit": unit, "omzet": _rp(omzet),
                  "hpp_cakupan_persen": _pct(unit_cov, unit) if unit else 0.0,
                  "laba_kotor": _rp(omzet_cov - hpp) if unit_cov else None,
                  "margin_persen": _pct(omzet_cov - hpp, omzet_cov) if omzet_cov > 0 else None},
        "baris": rows[:n],
        "catatan": ([] if not unit or unit_cov >= unit * 0.8 else
                    ["Cakupan HPP di bawah 80%: marjin hanya mewakili produk yang sudah punya HPP."])
                   + (["Produk tanpa penjualan pada periode ini tidak muncul di daftar terbawah."]
                      if urut == "terbawah" else []),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. TARGET vs AKTUAL PER TOKO PER BULAN
# ══════════════════════════════════════════════════════════════════════════════
def bulan_dalam(dari_bulan: str, sampai_bulan: str) -> List[str]:
    def ok(s: str, nama: str) -> Tuple[int, int]:
        try:
            y, m = int(str(s)[:4]), int(str(s)[5:7])
            date(y, m, 1)
            return y, m
        except (TypeError, ValueError):
            raise PeriodeSalah(f"Isian {nama} '{s}' bukan bulan yang sah (format TTTT-BB).") from None
    y0, m0 = ok(dari_bulan, "dari_bulan")
    y1, m1 = ok(sampai_bulan, "sampai_bulan")
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if len(out) > 24:
            raise PeriodeSalah("Rentang target paling panjang 24 bulan.")
    if not out:
        raise PeriodeSalah("Bulan 'sampai' lebih awal daripada bulan 'dari'.")
    return out


async def analitik_target(db, accounts: Sequence[dict], bulan: Sequence[str], *,
                          hari_ini: Optional[date] = None) -> dict:
    today = hari_ini or _today_wib()
    ids = [a["id"] for a in accounts]
    first, last = bulan[0], bulan[-1]
    # bulan Marketing = 26 bulan lalu … 25 (owner 11 Nov 2026)
    d0 = _bulan.rentang_periode(first)[0]
    d1 = _bulan.rentang_periode(last)[1]
    rows, _dup = await baca_rekap(db, ids, d0, d1)
    per: Dict[Tuple[str, str], List[dict]] = {}
    for r in rows:
        per.setdefault((r["account_id"], _bulan.periode_dari(r["date"])), []).append(r)
    targets: Dict[Tuple[str, str], dict] = {}
    years = sorted({int(b[:4]) for b in bulan})
    async for t in db[TARGETS].find({"account_id": {"$in": ids}, "year": {"$in": years}},
                                    {"_id": 0}):
        try:
            targets[(t["account_id"], f"{int(t['year']):04d}-{int(t['month']):02d}")] = t
        except (KeyError, TypeError, ValueError):
            continue
    baris = []
    tot = {"target_omzet": 0.0, "aktual_omzet": 0.0, "target_pesanan": 0, "aktual_pesanan": 0}
    for ym in bulan:
        y, m = int(ym[:4]), int(ym[5:7])
        dim = _bulan.jumlah_hari(y, m)
        berjalan = _bulan.bulan_dari(today) == (y, m)
        hari_lewat = _bulan.hari_berlalu(y, m, today)
        for a in accounts:
            t = targets.get((a["id"], ym)) or {}
            s = jumlahkan(per.get((a["id"], ym), []))
            tgt = _num(t.get("revenue_target")) or None
            tgt_o = _int(t.get("orders_target")) or None
            cap = _pct(s["omzet"], tgt) if tgt else None
            row = {"toko_id": a["id"], "toko": a.get("account_name"), "bulan": ym,
                   "label_bulan": label_bulan(ym), "rentang_bulan": _bulan.label(y, m), "target_omzet": _rp(tgt) if tgt else None,
                   "aktual_omzet": s["omzet"], "capaian_omzet_persen": cap,
                   "target_pesanan": tgt_o, "aktual_pesanan": s["pesanan"],
                   "capaian_pesanan_persen": _pct(s["pesanan"], tgt_o) if tgt_o else None,
                   "status": ("tanpa_target" if cap is None else "sesuai_jalur" if cap >= 90
                              else "waspada" if cap >= 70 else "tertinggal"),
                   "bulan_berjalan": berjalan, "hari_berlalu": hari_lewat, "hari_dalam_bulan": dim}
            if berjalan and hari_lewat:
                proj = s["omzet"] / hari_lewat * dim
                row["proyeksi_omzet_akhir_bulan"] = _rp(proj)
                row["proyeksi_capaian_persen"] = _pct(proj, tgt) if tgt else None
                if berjalan and cap is not None:
                    harus = tgt * hari_lewat / dim
                    row["status"] = ("sesuai_jalur" if s["omzet"] >= harus * 0.9 else
                                     "waspada" if s["omzet"] >= harus * 0.7 else "tertinggal")
            baris.append(row)
            tot["target_omzet"] += tgt or 0.0
            tot["aktual_omzet"] += s["omzet"]
            tot["target_pesanan"] += tgt_o or 0
            tot["aktual_pesanan"] += s["pesanan"]
    # M-04 — capaian gabungan hanya dari baris (toko × bulan) yang bertarget
    cap = capaian_gabungan(baris, lambda b: b["target_omzet"], lambda b: b["aktual_omzet"])
    catatan = ([] if any(b["target_omzet"] for b in baris)
               else ["Belum ada target toko pada bulan-bulan ini."])
    if cap["toko_bertarget"] and cap["toko_tanpa_target"]:
        catatan.append(f"Capaian gabungan dihitung dari {cap['toko_bertarget']} baris toko-bulan yang "
                       f"bertarget; omzet {cap['toko_tanpa_target']} baris tanpa target "
                       f"(Rp{_rp(cap['aktual_tanpa_target']):,.0f}) tidak ikut dibandingkan."
                       .replace(",", "."))
    return {"bulan": list(bulan), "definisi": DEFINISI_OMZET,
            "total": {"target_omzet": _rp(tot["target_omzet"]), "aktual_omzet": _rp(tot["aktual_omzet"]),
                      "capaian_omzet_persen": cap["persen"],
                      "aktual_omzet_bertarget": _rp(cap["aktual_bertarget"]),
                      "target_pesanan": tot["target_pesanan"], "aktual_pesanan": tot["aktual_pesanan"]},
            "baris": baris,
            "catatan": catatan}


# ══════════════════════════════════════════════════════════════════════════════
# 9. IKLAN: BELANJA, OMZET ATRIBUSI, ROAS (tanggal campur dinormalkan saat dibaca)
# ══════════════════════════════════════════════════════════════════════════════
def tanggal_iklan(doc: dict) -> Optional[str]:
    """Tanggal baris iklan ``YYYY-MM-DD`` apa pun tipe simpanannya (audit #6).

    Jenis impor ``ads`` menyimpan ``date`` sebagai datetime; laporan CPC Shopee
    dan entri lama menyimpan string. Dulu tren membuang semua baris string.
    """
    return kunci_tanggal(doc.get("date")) or kunci_tanggal(doc.get("period_start"))


MASA_IKLAN_MAKS = 92     # laporan lebih panjang dari ini tidak dibagi (dianggap salah isi)
LABEL_DIBAGI_RATA = "dibagi rata"


def rentang_iklan(doc: dict) -> Tuple[Optional[str], Optional[str]]:
    """Rentang belanja satu baris iklan → ``(awal, akhir)`` inklusif.

    Q-3 (keputusan owner 9 Nov 2026) — laporan per PERIODE (CPC Shopee 1–31 Agt) dulu
    membebankan SELURUH biaya pada tanggal awal: minggu pertama tampak boros, minggu lain
    "iklan belum diimpor". Baris berperiode sekarang dibagi rata per hari dalam periodenya.
    Baris tanpa periode = satu hari (tanggalnya sendiri).
    """
    ps, pe = kunci_tanggal(doc.get("period_start")), kunci_tanggal(doc.get("period_end"))
    if ps and pe and pe >= ps and jumlah_hari(ps, pe) <= MASA_IKLAN_MAKS:
        return ps, pe
    d = tanggal_iklan(doc)
    return d, d


def porsi_iklan(doc: dict, dari: str, sampai: str) -> float:
    """Bagian baris iklan yang jatuh di ``[dari, sampai]`` (0..1), dibagi rata per hari."""
    a, b = rentang_iklan(doc)
    if not a:
        return 0.0
    lo, hi = max(a, dari), min(b, sampai)
    if hi < lo:
        return 0.0
    return jumlah_hari(lo, hi) / jumlah_hari(a, b)


def pecah_harian_iklan(doc: dict, dari: str, sampai: str) -> List[Tuple[str, float]]:
    """Baris iklan → ``[(tanggal, porsi), …]`` untuk hari-hari di dalam ``[dari, sampai]``."""
    a, b = rentang_iklan(doc)
    if not a:
        return []
    lo, hi = max(a, dari), min(b, sampai)
    if hi < lo:
        return []
    n = jumlah_hari(a, b)
    d0 = date.fromisoformat(lo)
    return [((d0 + timedelta(days=i)).isoformat(), 1.0 / n) for i in range(jumlah_hari(lo, hi))]


def filter_iklan_rentang(dari: str, sampai: str) -> dict:
    """Saringan Mongo: baris bertanggal di rentang ATAU berperiode yang beririsan."""
    return {"$or": [filter_tanggal("date", dari, sampai),
                    {"period_start": {"$lte": sampai + "\uffff"}, "period_end": {"$gte": dari}}]}


async def baca_iklan(db, account_ids: Sequence[str], dari: str, sampai: str) -> List[dict]:
    """Baris iklan yang MENYENTUH rentang, masing-masing dengan ``_porsi`` (Q-3).

    ``_tanggal`` = hari pertama baris itu di dalam rentang; ``_dibagi_rata`` = baris
    berperiode lebih dari satu hari (biayanya dibagi rata per hari).
    """
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return []
    q = {"$and": [{"account_id": {"$in": ids}}, filter_iklan_rentang(dari, sampai),
                  dict(TANPA_CONTOH)]}
    out = []
    async for d in db[ADS].find(q, {"_id": 0}):
        porsi = porsi_iklan(d, dari, sampai)
        if porsi <= 0:
            continue
        a, b = rentang_iklan(d)
        d["_tanggal"] = max(a, dari)
        d["_porsi"] = porsi
        d["_dibagi_rata"] = bool(a and b and b > a)
        out.append(d)
    return out


def jalur_iklan(doc: dict) -> str:
    """Asal satu baris iklan: ``shopee_ads_cpc`` · ``ads`` (impor) · ``manual``."""
    if str(doc.get("source_report") or "") == "shopee_ads_cpc":
        return "shopee_ads_cpc"
    if doc.get("_import_session_id") or doc.get("_import_source_type"):
        return str(doc.get("_import_source_type") or "ads")
    return "manual"


LABEL_JALUR_IKLAN = {"shopee_ads_cpc": "impor Laporan Iklan Shopee (CPC)",
                     "ads": "impor Biaya & Performa Iklan", "manual": "entri manual"}


async def bentrok_iklan(db, account_id: str, rows: Sequence[Tuple[str, str, str]], *,
                        jalur: str, kecuali_id: Optional[str] = None) -> List[dict]:
    """M-09 — baris iklan JALUR LAIN untuk kampanye & hari yang sama.

    ``rows`` = ``[(nama_kampanye, awal, akhir), …]``. Dulu impor CPC Rp452.122 + entri manual
    kampanye & tanggal sama Rp8.693 dijumlah di semua layar (Rp460.815). Baris dari jalur
    yang SAMA tidak dihitung bentrok (itu ditangani kunci dedupe jalurnya: diperbarui).
    """
    rows = [(n, a, b) for n, a, b in rows if n and a and b]
    if not rows or not account_id:
        return []
    lo = min(a for _n, a, _b in rows)
    hi = max(b for _n, _a, b in rows)
    want: Dict[str, List[Tuple[str, str]]] = {}
    for n, a, b in rows:
        want.setdefault(_norm(n), []).append((a, b))
    q = {"$and": [{"account_id": account_id}, filter_iklan_rentang(lo, hi), dict(TANPA_CONTOH)]}
    out = []
    async for d in db[ADS].find(q, {"_id": 0}):
        if kecuali_id and d.get("id") == kecuali_id:
            continue
        if jalur_iklan(d) == jalur:
            continue
        spans = want.get(_norm(d.get("campaign_name")))
        if not spans:
            continue
        a, b = rentang_iklan(d)
        if a and any(not (b < x or a > y) for x, y in spans):
            out.append({"id": d.get("id"), "campaign_name": d.get("campaign_name"),
                        "dari": a, "sampai": b, "spend": _num(d.get("spend")),
                        "jalur": jalur_iklan(d)})
    return out


def pesan_bentrok_iklan(hits: Sequence[dict], *, saat: str) -> str:
    contoh = "; ".join(
        f"'{h['campaign_name']}' {h['dari']}{'' if h['dari'] == h['sampai'] else '..' + h['sampai']} "
        f"({LABEL_JALUR_IKLAN.get(h['jalur'], h['jalur'])}, Rp{round(h['spend']):,})".replace(",", ".")
        for h in list(hits)[:4])
    return (f"{saat} dibatalkan: biaya iklan kampanye yang sama pada hari yang sama sudah tercatat "
            f"lewat jalur lain — {contoh}. Kalau diteruskan, biaya iklan terhitung dua kali di "
            "ROAS & anggaran. Ubah/hapus baris yang lama, atau pakai satu jalur saja untuk kampanye ini.")


def _agg_iklan(rows: Sequence[dict]) -> dict:
    def tot(k: str) -> float:
        return sum(_num(r.get(k)) * float(r.get("_porsi", 1.0)) for r in rows)
    spend, rev = tot("spend"), tot("revenue")
    imp, clk, conv = tot("impressions"), tot("clicks"), tot("conversions")
    return {"belanja": _rp(spend), "omzet_atribusi": _rp(rev),
            "roas": round(rev / spend, 2) if spend else None,
            "impresi": int(round(imp)), "klik": int(round(clk)), "konversi": int(round(conv)),
            "ctr_persen": _pct(clk, imp, 2), "cpc": _rp(spend / clk) if clk else None,
            "biaya_per_konversi": _rp(spend / conv) if conv else None,
            "baris": len(rows),
            "dibagi_rata": sum(1 for r in rows if r.get("_dibagi_rata"))}


async def analitik_iklan(db, accounts: Sequence[dict], dari: str, sampai: str, *,
                         kelompok: str = "toko", limit: int = 20) -> dict:
    kelompok = (kelompok or "toko").strip().lower()
    pilihan = ("toko", "kampanye", "saluran", "hari", "minggu", "bulan")
    if kelompok not in pilihan:
        raise PeriodeSalah("Pilihan kelompok iklan harus salah satu dari: " + ", ".join(pilihan) + ".")
    toko = {a["id"]: a for a in accounts}
    rows = await baca_iklan(db, list(toko), dari, sampai)
    omzet = (await ringkas_omzet(db, accounts, dari, sampai))["total"]["omzet"]

    def key_of(r: dict) -> Tuple[str, str]:
        if kelompok == "toko":
            return r.get("account_id"), (toko.get(r.get("account_id")) or {}).get("account_name") or "-"
        if kelompok == "kampanye":
            nm = str(r.get("campaign_name") or "Tanpa nama")
            return f"{r.get('account_id')}|{_norm(nm)}", nm
        if kelompok == "saluran":
            # M-23 — saluran IKLAN (Shopee Ads/TikTok Ads/…), bukan platform toko
            s = str(r.get("ad_platform") or r.get("source_report") or r.get("platform") or "lainnya")
            return s, s.replace("_", " ").capitalize()
        return _kunci_waktu(r["_tanggal"], kelompok)

    if kelompok in KELOMPOK_WAKTU:
        # Q-3 — baris berperiode dipecah per hari supaya tren harian/mingguan tidak menumpuk
        expanded: List[dict] = []
        for r in rows:
            for day, frac in pecah_harian_iklan(r, dari, sampai):
                expanded.append({**r, "_tanggal": day, "_porsi": frac})
        group_rows = expanded
    else:
        group_rows = rows
    grp: Dict[str, List[dict]] = {}
    labels: Dict[str, str] = {}
    for r in group_rows:
        k, lab = key_of(r)
        grp.setdefault(k, []).append(r)
        labels[k] = lab
    out = [{"kunci": k, "label": labels[k], **_agg_iklan(rs)} for k, rs in grp.items()]
    if kelompok in KELOMPOK_WAKTU:
        out.sort(key=lambda r: r["kunci"])
    else:
        out.sort(key=lambda r: -r["belanja"])
    n = max(1, min(int(limit or 20), 400))
    total = _agg_iklan(rows)
    total["omzet_toko"] = omzet
    total["rasio_iklan_terhadap_omzet_persen"] = _pct(total["belanja"], omzet, 2)
    catatan = ["Omzet atribusi = omzet yang dilaporkan platform iklan, bukan omzet rekap toko.",
               "ROAS = omzet atribusi iklan ÷ biaya iklan. Rasio iklan terhadap omzet = biaya iklan "
               "÷ omzet seluruh toko pada periode yang sama."]
    if total["dibagi_rata"]:
        catatan.append(f"{total['dibagi_rata']} laporan iklan berperiode: biayanya {LABEL_DIBAGI_RATA} "
                       "per hari dalam periode laporan, lalu hanya hari di dalam rentang ini yang "
                       "dihitung.")
    if not rows:
        catatan.append("Belum ada data iklan pada periode ini (ROAS tidak bisa dihitung, bukan 0).")
    return {"periode": {"dari": dari, "sampai": sampai}, "kelompok": kelompok,
            "total": total, "baris": out[:n], "jumlah_baris": len(out),
            "dipotong": len(out) > n, "catatan": catatan}


# ══════════════════════════════════════════════════════════════════════════════
# 10. LIVE: SESI, OMZET, PESANAN PER HOST/TOKO
# ══════════════════════════════════════════════════════════════════════════════
def _live_num(d: dict, *names: str) -> float:
    for n in names:
        if d.get(n) is not None:
            return _num(d.get(n))
    return 0.0


DEFINISI_LIVE = (
    "Omzet live resmi = omzet pesanan berkanal LIVE (kolom kanal di ekspor pesanan), dibaca dari "
    "rekap harian (`kanal.live`) — bagian dari omzet toko, bukan tambahan. Angka yang diketik di "
    "sesi live, shift host, atau sesi kreator adalah CATATAN KERJA dan pembanding, tidak dijumlah "
    "sebagai omzet. Sesi berstatus batal tidak dihitung.")


async def ringkas_live(db, accounts: Sequence[dict], dari: str, sampai: str) -> dict:
    """Q-2 (keputusan owner 9 Nov 2026) — SATU definisi omzet live untuk semua layar.

    Dulu satu siaran yang sama tampil Rp289.427 (analitik), Rp578.854 (Dashboard: shift host
    + sesi kreator dijumlah), dan Rp789.427 (layar Sesi Live: sesi batal ikut).
    → ``{omzet, pesanan, sesi, omzet_tercatat_sesi, selisih, ...}``.
    """
    ids = [a["id"] for a in accounts if a.get("id")]
    oms = await ringkas_omzet(db, accounts, dari, sampai)
    per_hari: Dict[Tuple[str, str], float] = {}
    turunan = set()
    for r in oms["baris"]:
        per_hari[(r["account_id"], r["date"])] = _num((r.get("kanal") or {}).get("live"))
        if r.get("sumber") == _shape.SOURCE_ORDERS_AUTO:
            turunan.add((r["account_id"], r["date"]))
    # Toko REKAP MANUAL (tanpa ekspor pesanan): angka live yang DIKETIK di rekap jenis "live"
    # dipakai untuk hari yang tidak punya pesanan turunan & tidak punya kanal live di rekap
    # total. Rekap live hasil sinkron shift/sesi kreator TIDAK dipakai (catatan kerja, Q-2).
    live_rows, _dup = await baca_rekap(db, ids, dari, sampai, revenue_type="live")
    for r in live_rows:
        key = (r["account_id"], r["date"])
        if (r.get("sumber") in (_shape.SOURCE_MANUAL, _shape.SOURCE_IMPORT, _shape.SOURCE_TASK,
                                _shape.SOURCE_MANUAL_OVERRIDE)
                and key not in turunan and not per_hari.get(key)):
            per_hari[key] = _num(r.get("omzet"))
    omzet = sum(per_hari.values())
    per_toko: Dict[str, float] = {}
    per_tanggal: Dict[str, float] = {}
    for (aid, d), v in per_hari.items():
        per_toko[aid] = per_toko.get(aid, 0.0) + v
        per_tanggal[d] = per_tanggal.get(d, 0.0) + v
    orders = await baca_pesanan(db, ids, dari, sampai)
    pesanan = sum(1 for o in orders if kanal_pesanan(o) == "live")
    sesi = 0
    tercatat = 0.0
    if ids:
        q = {"$and": [{"account_id": {"$in": ids}}, filter_tanggal("session_date", dari, sampai),
                      dict(TANPA_CONTOH), {"status": {"$ne": "cancelled"}}]}
        async for d in db[LIVE].find(q, {"_id": 0, "session_date": 1, "revenue": 1, "gmv": 1}):
            k = kunci_tanggal(d.get("session_date"))
            if k and dari <= k <= sampai:
                sesi += 1
                tercatat += _live_num(d, "revenue", "gmv")
    return {"omzet": _rp(omzet), "pesanan": pesanan, "sesi": sesi,
            "omzet_tercatat_sesi": _rp(tercatat), "selisih_tercatat": _rp(tercatat - omzet),
            "per_toko": {k: _rp(v) for k, v in per_toko.items()},
            # Dashboard Marketing (14 Nov 2026) — grafik harian memakai angka yang SAMA dengan kartu
            # "Termasuk live"; tanpa ini layar menjumlah rekap jenis "live" (catatan kerja, Q-2).
            "per_tanggal": {k: _rp(v) for k, v in sorted(per_tanggal.items())},
            "definisi": DEFINISI_LIVE}


async def analitik_live(db, accounts: Sequence[dict], dari: str, sampai: str, *,
                        kelompok: str = "host", limit: int = 20) -> dict:
    kelompok = (kelompok or "host").strip().lower()
    pilihan = ("host", "toko", "hari", "minggu", "bulan")
    if kelompok not in pilihan:
        raise PeriodeSalah("Pilihan kelompok live harus salah satu dari: " + ", ".join(pilihan) + ".")
    toko = {a["id"]: a for a in accounts}
    ids = list(toko)
    rows: List[dict] = []
    if ids:
        q = {"$and": [{"account_id": {"$in": ids}}, filter_tanggal("session_date", dari, sampai),
                      dict(TANPA_CONTOH)]}
        async for d in db[LIVE].find(q, {"_id": 0}):
            k = kunci_tanggal(d.get("session_date"))
            if k and dari <= k <= sampai and str(d.get("status") or "") != "cancelled":
                d["_tanggal"] = k
                rows.append(d)

    def agg(rs: Sequence[dict]) -> dict:
        rev = sum(_live_num(r, "revenue", "gmv") for r in rs)
        ords = sum(_live_num(r, "orders", "total_orders") for r in rs)
        menit = sum(_live_num(r, "duration_minutes") for r in rs)
        view = sum(_live_num(r, "total_viewers", "viewers") for r in rs)
        return {"sesi": len(rs), "omzet": _rp(rev), "pesanan": int(ords),
                "jam_live": round(menit / 60, 1), "penonton": int(view),
                "omzet_per_jam": _rp(rev / (menit / 60)) if menit else None,
                "konversi_persen": _pct(ords, view, 2)}

    def key_of(r: dict) -> Tuple[str, str]:
        if kelompok == "host":
            return str(r.get("host_id") or r.get("host_name") or "-"), r.get("host_name") or "Tanpa host"
        if kelompok == "toko":
            return r.get("account_id"), (toko.get(r.get("account_id")) or {}).get("account_name") or "-"
        return _kunci_waktu(r["_tanggal"], kelompok)

    grp: Dict[str, List[dict]] = {}
    labels: Dict[str, str] = {}
    for r in rows:
        k, lab = key_of(r)
        grp.setdefault(k, []).append(r)
        labels[k] = lab
    out = [{"kunci": k, "label": labels[k], **agg(rs)} for k, rs in grp.items()]
    out.sort(key=(lambda r: r["kunci"]) if kelompok in KELOMPOK_WAKTU else (lambda r: -r["omzet"]))
    n = max(1, min(int(limit or 20), 400))
    total = agg(rows)
    resmi = await ringkas_live(db, accounts, dari, sampai)
    # Q-2 — `omzet` sesi tetap ada (pembanding per host/sesi), tetapi angka RESMI-nya
    # `omzet_live_pesanan`; selisihnya = kualitas data pencatatan sesi.
    total["omzet_tercatat_sesi"] = total["omzet"]
    total["omzet_live_pesanan"] = resmi["omzet"]
    total["pesanan_live_pesanan"] = resmi["pesanan"]
    total["selisih_tercatat_vs_pesanan"] = _rp(total["omzet"] - resmi["omzet"])
    return {"periode": {"dari": dari, "sampai": sampai}, "kelompok": kelompok,
            "total": total, "baris": out[:n], "jumlah_baris": len(out),
            "dipotong": len(out) > n, "definisi": DEFINISI_LIVE,
            "catatan": (["Omzet live RESMI = pesanan berkanal LIVE (omzet_live_pesanan). Omzet per "
                         "host/sesi di tabel = angka yang dicatat di sesi (pembanding, bukan omzet "
                         "resmi)."] + ([] if rows else ["Belum ada sesi live pada periode ini."]))}


# ══════════════════════════════════════════════════════════════════════════════
# 11. SETORAN (DANA DILEPAS): BRUTO, BIAYA PER JENIS, NETO — per settlement_date
# ══════════════════════════════════════════════════════════════════════════════
BIAYA_SETORAN = {
    "platform_commission": "Komisi platform",
    "platform_service_fee": "Biaya layanan",
    "affiliate_commission": "Komisi afiliasi",
    "ads_deduction": "Potongan iklan",
    "other_deductions": "Potongan lain",
}
UANG_SETORAN = ("gross_sales", "refunds", "seller_discount", "shipping_subsidy", "adjustments",
                "net_payout", *BIAYA_SETORAN)


async def analitik_setoran(db, accounts: Sequence[dict], dari: str, sampai: str, *,
                           kelompok: str = "toko", limit: int = 50) -> dict:
    kelompok = (kelompok or "toko").strip().lower()
    pilihan = ("toko", "platform", "bulan")
    if kelompok not in pilihan:
        raise PeriodeSalah("Pilihan kelompok setoran harus salah satu dari: " + ", ".join(pilihan) + ".")
    toko = {a["id"]: a for a in accounts}
    rows: List[dict] = []
    if toko:
        q = {"account_id": {"$in": list(toko)}, "settlement_date": {"$gte": dari, "$lte": sampai + "￿"},
             **TANPA_CONTOH}
        async for d in db[SETTLEMENTS].find(q, {"_id": 0}):
            k = kunci_tanggal(d.get("settlement_date"))
            if k and dari <= k <= sampai:
                d["_tanggal"] = k
                rows.append(d)

    def agg(rs: Sequence[dict]) -> dict:
        s = {f: sum(_num(r.get(f)) for r in rs) for f in UANG_SETORAN}
        biaya = {BIAYA_SETORAN[f]: _rp(s[f]) for f in BIAYA_SETORAN}
        tb = sum(s[f] for f in BIAYA_SETORAN)
        return {"setoran": len(rs), "bruto": _rp(s["gross_sales"]), "refund": _rp(s["refunds"]),
                "diskon_penjual": _rp(s["seller_discount"]), "subsidi_ongkir": _rp(s["shipping_subsidy"]),
                "penyesuaian": _rp(s["adjustments"]), "biaya": biaya, "total_biaya": _rp(tb),
                "biaya_persen_dari_bruto": _pct(tb, s["gross_sales"], 2),
                "neto_diterima": _rp(s["net_payout"])}

    def key_of(r: dict) -> Tuple[str, str]:
        if kelompok == "toko":
            return r.get("account_id"), (toko.get(r.get("account_id")) or {}).get("account_name") or "-"
        if kelompok == "platform":
            p = _platform(r.get("platform") or (toko.get(r.get("account_id")) or {}).get("platform"))
            return p, p.capitalize()
        return r["_tanggal"][:7], label_bulan(r["_tanggal"][:7])

    grp: Dict[str, List[dict]] = {}
    labels: Dict[str, str] = {}
    for r in rows:
        k, lab = key_of(r)
        grp.setdefault(k, []).append(r)
        labels[k] = lab
    out = [{"kunci": k, "label": labels[k], **agg(rs)} for k, rs in grp.items()]
    out.sort(key=(lambda r: r["kunci"]) if kelompok == "bulan" else (lambda r: -r["bruto"]))
    n = max(1, min(int(limit or 50), 400))
    return {"periode": {"dari": dari, "sampai": sampai}, "kelompok": kelompok,
            "dasar_tanggal": "tanggal dana dilepas (settlement_date)",
            "total": agg(rows), "baris": out[:n], "jumlah_baris": len(out),
            "dipotong": len(out) > n,
            "catatan": ["Biaya platform hanya dari laporan dana dilepas; tanggalnya tanggal dana dilepas, "
                        "bukan tanggal pesanan."] + ([] if rows else ["Belum ada laporan dana dilepas pada periode ini."])}
