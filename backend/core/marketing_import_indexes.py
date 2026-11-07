"""core.marketing_import_indexes — indeks UNIK untuk kunci dedup impor Marketing.

KENAPA (audit AI 7 Nov 2026, §3.C #11)
-------------------------------------
Wizard Impor mencegah baris kembar dengan MEMBACA dulu (`find_one(kunci)`), lalu
menyisipkan. Tanpa indeks unik, dua sesi impor yang berjalan bersamaan (atau satu
klik ganda) sama-sama tidak menemukan kembarannya dan sama-sama menyisipkan:
biaya iklan, retur, dan sesi live terhitung dua kali tanpa satu pun galat.

Indeks diturunkan LANGSUNG dari kamus jenis impor (`SourceType.dedupe`), jadi jenis
impor baru otomatis ikut. Setiap indeks:

* hanya berlaku untuk baris hasil impor jenis itu (``_import_source_type``) —
  entri manual dan jenis lain di koleksi yang sama tidak terganggu;
* hanya berlaku bila SEMUA bagian kuncinya terisi (nilai kosong memang dilewati
  pemeriksa dedup, jadi tidak boleh membuat sisipan gagal).

`marketing_orders` dan `marketing_sales_data` sudah punya indeks unik umum sejak F0.5
(lihat `migrations/ensure_indexes.py`); keduanya ikut DIPERIKSA duplikatnya oleh
migrasi `scripts/migrations/2026_11_08_cek_duplikat_impor_marketing.py` tetapi
tidak dibuatkan indeks kedua di sini.
"""
from __future__ import annotations

from typing import Dict, List

# Jenis yang sudah dipagari indeks unik UMUM (bukan per jenis impor).
SUDAH_DIPAGARI = {
    "marketplace_orders": "uniq_order_account_platform_orderid",
    "orders": "uniq_order_account_platform_orderid",
    "sales_daily": "uniq_sales_account_date_type",
}

# Indeks umum yang juga diperiksa duplikatnya (dibuat di ensure_indexes sejak F0.5).
INDEKS_UMUM = [
    {"collection": "marketing_sales_data", "name": "uniq_sales_account_date_type",
     "keys": [("account_id", 1), ("date", 1), ("revenue_type", 1)], "partial": None,
     "label": "Rekap harian (toko, tanggal, jenis)", "source_type": None},
    {"collection": "marketing_orders", "name": "uniq_order_account_platform_orderid",
     "keys": [("account_id", 1), ("platform", 1), ("order_id", 1)],
     "partial": {"order_id": {"$exists": True}},
     "label": "Pesanan (toko, platform, nomor pesanan)", "source_type": None},
]


def _syarat_terisi(kind: str) -> Dict[str, object]:
    """Saringan 'bagian kunci terisi' yang boleh dipakai indeks parsial."""
    if kind == "datetime":
        return {"$type": "date"}
    if kind in ("int", "money", "num", "pct"):
        return {"$type": "number"}
    return {"$gt": ""}          # teks tidak kosong (perbandingan BSON hanya antar-teks)


def unique_import_specs() -> List[dict]:
    """Daftar indeks unik per jenis impor: ``{collection, name, keys, partial, ...}``."""
    from core.marketing_import_schema import get_source_type, source_type_catalog
    out: List[dict] = []
    for t in source_type_catalog():
        st = get_source_type(t["key"])
        if st.update_only or not st.dedupe or st.key in SUDAH_DIPAGARI:
            continue
        partial: Dict[str, object] = {"_import_source_type": st.key}
        for k in st.dedupe:
            try:
                kind = st.field(k).kind
            except Exception:  # noqa: BLE001 — bagian kunci tanpa definisi field
                kind = "str"
            partial[k] = _syarat_terisi(kind)
        out.append({"collection": st.collection, "name": f"uniq_impor_{st.key}",
                    "keys": [(k, 1) for k in st.dedupe], "partial": partial,
                    "label": st.label, "source_type": st.key})
    return out


def all_specs() -> List[dict]:
    """Indeks umum + indeks per jenis impor (urutan tetap)."""
    return [dict(s) for s in INDEKS_UMUM] + unique_import_specs()


async def find_duplicates(db, spec: dict, *, sample: int = 5) -> dict:
    """Kelompok kunci yang punya lebih dari satu dokumen (yang akan menggagalkan indeks)."""
    match = dict(spec.get("partial") or {})
    group_id = {k.replace(".", "_"): f"${k}" for k, _ in spec["keys"]}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": group_id, "n": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"n": -1}},
    ]
    groups = 0
    extra = 0
    contoh = []
    async for g in db[spec["collection"]].aggregate(pipeline, allowDiskUse=True):
        groups += 1
        extra += int(g["n"]) - 1
        if len(contoh) < sample:
            contoh.append({"kunci": {k: str(v) for k, v in (g["_id"] or {}).items()},
                           "jumlah": int(g["n"]), "id": [str(i) for i in (g.get("ids") or [])[:5]]})
    return {"kelompok_kembar": groups, "dokumen_berlebih": extra, "contoh": contoh}


async def index_exists(db, spec: dict) -> bool:
    try:
        info = await db[spec["collection"]].index_information()
    except Exception:  # noqa: BLE001 — koleksi belum ada
        return False
    return spec["name"] in info
