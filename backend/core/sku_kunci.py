"""core.sku_kunci — tautan baris pesanan/retur ke barang TANPA menebak varian.

KENAPA BERKAS INI ADA (audit Gudang × Pesanan 9 Nov 2026, G3 & G4)
-----------------------------------------------------------------
* **G3 — tautan lewat NAMA mengabaikan variasi.** Katalog toko memakai SATU nama produk
  untuk banyak varian (28 nama dipakai > 1 SKU FG: kulot rayon panjang, keiko, …). Pencocokan
  lama `items_by_name[norm(nama)]` memilih item TERAKHIR bernama sama, sehingga pesanan
  "Kulot Rayon Panjang / Maroon,M" tertaut ke DA-5504-MRN-XL — dan retur impor bisa menambah
  stok SKU yang salah. Aturan sekarang (:func:`pilih_lewat_nama`): nama hanya dipakai bila
  nama + variasi menunjuk TEPAT SATU item katalog toko itu; selain itu baris dibiarkan tak
  tertaut dengan alasan yang bisa ditindaklanjuti di layar Pemetaan SKU.
* **G4 — baris tanpa SKU platform tidak bisa dipetakan.** Ekspor Shopee sering mengosongkan
  "SKU Induk"/"Nomor Referensi SKU". Jembatan SKU dan Pemetaan SKU hanya mengenal
  `platform_sku_id`, jadi baris seperti itu tidak punya jalan apa pun untuk ditautkan.
  :func:`kunci_baris` memberi kunci pemetaan ``nv:<toko>:<nama>|<variasi>`` untuk baris tanpa
  SKU platform; kunci itu disimpan di item katalog (`bridge_keys`) supaya impor berikutnya
  ikut tertaut, dan diterapkan ke pesanan & retur lama yang menunggu.

Murni (tanpa DB) supaya bisa diuji dan dipakai impor, Jembatan SKU, dan Pemetaan SKU.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

PREFIX = "nv:"
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def norm(s: Any) -> str:
    """Huruf kecil, tanda baca → satu spasi (kata tetap terpisah)."""
    return _NON_ALNUM.sub(" ", str(s or "").lower()).strip()


def _flat(s: Any) -> str:
    return norm(s).replace(" ", "")


# ── G4 — kunci pemetaan ──────────────────────────────────────────────────────
def kunci_baris(line: dict, account_id: Optional[str]) -> str:
    """Kunci pemetaan satu baris item: SKU platform bila ada, kalau tidak nama+variasi per toko."""
    psid = str((line or {}).get("platform_sku_id") or "").strip()
    if psid:
        return psid
    name = norm((line or {}).get("product_name_raw") or (line or {}).get("product_name")
                or (line or {}).get("product"))
    if not name:
        return ""
    var = norm((line or {}).get("variation_raw") or (line or {}).get("variation"))
    return f"{PREFIX}{account_id or ''}:{name}|{var}"


def kunci_nama(key: Any) -> bool:
    return str(key or "").startswith(PREFIX)


def akun_kunci(key: str) -> Optional[str]:
    if not kunci_nama(key):
        return None
    rest = key[len(PREFIX):]
    return rest.split(":", 1)[0] or None


def label_kunci(key: str) -> str:
    """Teks untuk layar (tanpa istilah program)."""
    if not kunci_nama(key):
        return key
    rest = key[len(PREFIX):].split(":", 1)[-1]
    name, _sep, var = rest.partition("|")
    return f"Tanpa SKU platform — {name}" + (f" ({var})" if var else "")


# ── G3 — pilih item katalog lewat nama TANPA menebak varian ─────────────────
def _attrs(item: dict) -> Tuple[str, str]:
    color = str(item.get("fg_color") or item.get("color") or "").strip()
    size = str(item.get("fg_size") or item.get("size") or "").strip()
    if not (color or size):
        info = str(item.get("variant_info") or "")
        m = re.search(r"warna\s*:\s*([^|,]+)", info, re.I)
        if m:
            color = m.group(1).strip()
        m = re.search(r"(?:size|ukuran)\s*:\s*([^|,]+)", info, re.I)
        if m:
            size = m.group(1).strip()
    return color, size


def variasi_cocok(item: dict, variation: Any) -> Optional[bool]:
    """``True`` warna & ukuran item ada di teks variasi · ``False`` bertentangan ·
    ``None`` tidak bisa dipastikan (item tanpa warna/ukuran, atau variasi kosong)."""
    color, size = _attrs(item or {})
    var = norm(variation)
    if not (color or size):
        return True if not var else None
    if not var:
        return None
    toks = set(var.split())
    flat = var.replace(" ", "")
    if color and _flat(color) not in flat:
        return False
    if size:
        s = _flat(size)
        if not (s in toks or (len(s) > 2 and s in flat)):
            return False
    return True


def indeks_nama(items: Iterable[dict]) -> Dict[str, List[dict]]:
    """``norm(nama) → [item, …]`` (SEMUA item bernama sama, bukan yang terakhir)."""
    out: Dict[str, List[dict]] = {}
    for it in items or []:
        k = _flat(it.get("name"))
        if k:
            out.setdefault(k, []).append(it)
    return out


def pilih_lewat_nama(by_name_all: Dict[str, List[dict]], name: Any, variation: Any = "",
                     *, punya_variasi: bool = True) -> Tuple[Optional[dict], str]:
    """→ ``(item | None, alasan)``. Alasan kosong = tidak ada item bernama itu.

    ``punya_variasi=False`` untuk berkas yang memang tidak membawa kolom variasi (rincian
    produk live): nama harus unik di katalog toko.
    """
    cands = by_name_all.get(_flat(name)) or []
    if not cands:
        return None, ""
    if not punya_variasi:
        if len(cands) == 1:
            return cands[0], ""
        return None, (f"Nama produk '{name}' dipakai {len(cands)} item katalog toko ini — pakai "
                      "SKU supaya barangnya pasti.")
    hits = [c for c in cands if variasi_cocok(c, variation) is True]
    if len(hits) == 1:
        return hits[0], ""
    if len(hits) > 1:
        return None, (f"Nama '{name}' + variasi '{variation or '-'}' cocok ke {len(hits)} item "
                      "katalog — tautkan manual di Pemetaan SKU.")
    if len(cands) == 1 and variasi_cocok(cands[0], variation) is None:
        return None, (f"Nama '{name}' ada di katalog, tetapi variasinya ('{variation or '-'}') "
                      "tidak bisa dipastikan sama dengan warna/ukuran item itu — tautkan "
                      "manual di Pemetaan SKU.")
    return None, (f"Nama '{name}' ada di katalog, tetapi tidak ada item dengan variasi "
                  f"'{variation or '-'}' — tautkan manual di Pemetaan SKU.")
