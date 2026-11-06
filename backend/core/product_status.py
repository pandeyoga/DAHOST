"""core.product_status — SATU-SATUNYA aturan **status produk** (status jual / siklus hidup) per varian SKU.

Keputusan owner (6 Nov 2026): status disimpan per varian di `rahaza_model_variants.product_status`.
Nama field dan kodenya KONTRAK TETAP — skrip data mengisinya dari buku kerja permintaan cutting.

    kode          label
    new           Baru
    best_seller   Best Seller
    slow          Slow
    dead          Dead
    stop          Stop

Kosong / null = "belum diisi" (sah). Nilai lain ditolak (400 di route).

Status MODEL (`product_status_summary`) dihitung SAAT DIBACA dari varian aktif — pola yang sama dengan
`active` di daftar model dan `catalog_status`: tidak ada salinan yang bisa basi bila skrip data menulis
langsung ke varian. Aturan ringkasan ada di `summarize()`.

`stop` = Request Cutting tidak merencanakan SKU ini. Varian TIDAK dinonaktifkan otomatis (tetap dijual
sampai stok habis); daftar yang mengusulkan restock melewatinya dan menyebut alasannya (`STOP_REASON`).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional

FIELD = "product_status"
SUMMARY_FIELD = "product_status_summary"

CODES = ("new", "best_seller", "slow", "dead", "stop")
LABELS = {"new": "Baru", "best_seller": "Best Seller", "slow": "Slow", "dead": "Dead", "stop": "Stop"}
MIXED = "campuran"
MIXED_LABEL = "Campuran"
UNSET_LABEL = "Belum diisi"
UNSET_FILTER = "belum_diisi"          # nilai penyaring untuk varian yang statusnya kosong
STOP = "stop"
STOP_REASON = "Status produk Stop — tidak direncanakan cutting"

def _key(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


# kode & label sama-sama diterima: "best_seller" / "Best Seller" / "BEST SELLER" → best_seller
_ALIASES = {**{_key(c): c for c in CODES}, **{_key(v): k for k, v in LABELS.items()}}


class ProductStatusError(ValueError):
    """Nilai status produk tidak dikenal — pesannya siap ditampilkan ke staf."""


def choices_text() -> str:
    return ", ".join(LABELS[c] for c in CODES)


def parse(value) -> Optional[str]:
    """Kode atau label (huruf besar/kecil, spasi/garis bawah bebas) → kode. Kosong → None.

    Dipakai oleh endpoint varian DAN importir Excel, jadi "Best Seller", "best_seller",
    dan "BEST SELLER" semuanya diterima.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProductStatusError(f"Status produk harus teks. Pilihan: {choices_text()} (atau kosongkan).")
    if not value.strip():
        return None
    code = _ALIASES.get(_key(value))
    if not code:
        raise ProductStatusError(f"Status produk '{value.strip()}' tidak dikenal. "
                                 f"Pilihan: {choices_text()} (atau kosongkan = belum diisi).")
    return code


def label(code: Optional[str]) -> str:
    if not code:
        return UNSET_LABEL
    if code == MIXED:
        return MIXED_LABEL
    return LABELS.get(code, code)


def filter_query(value: Optional[str]) -> dict:
    """Penyaring daftar varian: `best_seller`, `stop,dead`, `belum_diisi` (boleh label juga).

    Kosong → {} (tanpa penyaring). Nilai tak dikenal → ProductStatusError.
    """
    if value is None or not str(value).strip():
        return {}
    wanted: list = []
    for part in str(value).split(","):
        if not part.strip():
            continue
        if _key(part) in (_key(UNSET_FILTER), _key(UNSET_LABEL)):
            wanted.extend([None, ""])          # null juga cocok dengan field yang tidak ada
        else:
            wanted.append(parse(part))
    return {FIELD: {"$in": wanted}} if wanted else {}


def summarize(statuses: Iterable[Optional[str]]) -> dict:
    """Ringkasan status model dari status varian AKTIF.

    * Semua varian berstatus sama → status itu.
    * Berbeda-beda → `campuran`; `dominant` = status yang paling banyak (seri → urutan CODES).
    * Varian yang belum diisi tidak dihitung sebagai status yang berbeda (`unset` melaporkan jumlahnya).
    * Belum ada yang diisi → code None ("Belum diisi").
    """
    counts: Counter = Counter()
    unset = 0
    for s in statuses:
        if s in LABELS:
            counts[s] += 1
        else:
            unset += 1
    dominant = None
    if counts:
        dominant = sorted(counts, key=lambda c: (-counts[c], CODES.index(c)))[0]
    code = dominant if len(counts) == 1 else (MIXED if counts else None)
    return {
        "code": code,
        "label": label(code),
        "dominant": dominant,
        "dominant_label": label(dominant) if dominant else "",
        "counts": {c: counts[c] for c in CODES if counts[c]},
        "unset": unset,
        "total": unset + sum(counts.values()),
    }


async def model_summaries(db, model_ids: Optional[list] = None, *, limit: int = 50000) -> dict:
    """{model_id: summarize(...)} dari varian aktif — satu kueri, proyeksi kecil."""
    q: dict = {"active": True}
    if model_ids is not None:
        q["model_id"] = {"$in": [m for m in model_ids if m]}
    per_model: dict = {}
    rows = await db.rahaza_model_variants.find(q, {"_id": 0, "model_id": 1, FIELD: 1}).to_list(limit)
    for v in rows:
        per_model.setdefault(v.get("model_id"), []).append(v.get(FIELD))
    return {mid: summarize(sts) for mid, sts in per_model.items() if mid}


async def stop_skus(db, skus: Iterable[str]) -> set:
    """SKU (dari daftar) yang variannya berstatus `stop` — untuk daftar usulan restock/cutting."""
    wanted = sorted({str(s).strip() for s in skus if s and str(s).strip()})
    if not wanted:
        return set()
    rows = await db.rahaza_model_variants.find(
        {"sku": {"$in": wanted}, FIELD: STOP}, {"_id": 0, "sku": 1}).to_list(len(wanted) * 4)
    return {r.get("sku") for r in rows if r.get("sku")}
