"""core.reference_dedup — satu aturan "nama master ini sudah ada" untuk data referensi.

2026-11-06 (pola P8). Data referensi tercatat dua kali karena setiap layar tambah master hanya
mencocokkan KODE persis (atau tidak mencocokkan apa pun):
  * kategori aset ×2 — benih otomatis berjalan dua kali bersamaan (7 pasang kembar);
  * proses "Jahit (CMT)" (SEWING) dan "Jahit / Sewing" (JAHIT), "Rework/Revisi" dan "Permak / Rework";
  * satuan "rol" / "gulung" / "roll" dan "pak" / "pack";
  * kategori produk "Set/Setelan" dan "One set".

Kunci banding memakai `core.variant_identity.norm` (huruf kecil, tanda baca → spasi — logika yang
sama dengan identitas warna), lalu:
  * sinonim Indonesia/Inggris & ejaan satuan disatukan per kata (sewing = jahit, roll = rol = gulung,
    buah = pcs, stel = set, lain-lain = lainnya …);
  * kata sambung (dan, &) dibuang dan urutan kata diabaikan ("Perabot & Mebel" = "Mebel dan Perabot").
Nuansa TIDAK digabung: "Kancing 22L" ≠ "Kancing 28L", "Benang" ≠ "Benang Jahit".

Dipakai oleh endpoint tambah/ubah master (`assert_unique_ref`) dan migrasi
`scripts/migrations/2026_11_07_gabung_data_referensi.py` — satu aturan untuk keduanya.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from core.variant_identity import norm

#: Sinonim per kata → bentuk kanonik. Hanya kata yang BENAR-BENAR sama artinya.
WORD_SYNONYMS = {
    "sewing": "jahit", "sew": "jahit",
    "rework": "permak", "revisi": "permak",
    "rol": "roll", "rolls": "roll", "gulung": "roll", "gulungan": "roll",
    "pak": "pack", "packs": "pack",
    "buah": "pcs", "pieces": "pcs", "piece": "pcs",
    "stel": "set", "setelan": "set",
    "lain": "lainnya", "other": "lainnya", "others": "lainnya",
    "jacket": "jaket",
    "fabric": "kain",
    "accessory": "aksesoris", "accessories": "aksesoris",
    "warehouse": "gudang", "office": "kantor",
    "pasang": "pair",
}
#: Frasa → satu kata (dicek sebelum per kata).
PHRASES = (
    ("one set", "set"),
    ("lain lain", "lainnya"),
)
STOPWORDS = {"dan", "and"}

#: Kode proses yang setara (pakai himpunan yang sudah dipakai HPP: `core.product_costing`).
REWORK_PROCESS_CODES = frozenset({"REWORK", "PERMAK"})


def ref_key(name) -> str:
    """Nama master → kunci banding ('' bila kosong)."""
    n = norm(name)
    if not n:
        return ""
    for phrase, rep in PHRASES:
        n = re.sub(rf"\b{phrase}\b", rep, n)
    toks = {WORD_SYNONYMS.get(t, t) for t in n.split() if t not in STOPWORDS}
    return " ".join(sorted(toks))


def process_class(code) -> str:
    """Kode proses → kelas setara (SEWING/JAHIT/CMT/SEW → SEWING; REWORK/PERMAK → REWORK)."""
    from core.product_costing import CMT_PROCESS_CODES
    c = str(code or "").strip().upper()
    if c in CMT_PROCESS_CODES:
        return "SEWING"
    if c in REWORK_PROCESS_CODES:
        return "REWORK"
    return c


def _active(doc: dict) -> bool:
    return (doc.get("active") is not False and doc.get("is_active") is not False
            and str(doc.get("status") or "").lower() not in ("inactive", "archived", "nonaktif"))


async def find_duplicate_ref(db, coll: str, *, name, name_field: str = "name",
                             exclude_id: str | None = None, id_field: str = "id",
                             process_code: str | None = None, scope: dict | None = None,
                             key_fn=None) -> dict | None:
    """Baris AKTIF lain di `coll` yang namanya sama menurut `ref_key` (atau kelas kode proses sama).

    `scope` membatasi banding ke baris dengan nilai field yang sama (mis. jabatan per unit).
    `key_fn` mengganti `ref_key` (warna memakai `variant_identity.color_group_key`, keputusan 6a).
    """
    key_fn = key_fn or ref_key
    key = key_fn(name) if norm(name) else ""
    pclass = process_class(process_code) if process_code else ""
    if not key and not pclass:
        return None
    async for d in db[coll].find({}, {"_id": 0}):
        if exclude_id and d.get(id_field) == exclude_id:
            continue
        if not _active(d):
            continue
        if scope and any((d.get(k) or None) != (v or None) for k, v in scope.items()):
            continue
        if key and norm(d.get(name_field)) and key_fn(d.get(name_field)) == key:
            return d
        if pclass and process_class(d.get("code")) == pclass:
            return d
    return None


#: Ambang kemiripan ejaan (difflib) untuk peringatan "nama mirip" — "operator cuting" vs "operator cutting" = 0,97;
#: "spv cuting" vs "spv gudang" = 0,70 (tidak diperingatkan).
SIMILAR_CUTOFF = 0.85


def similar_ref(a, b, cutoff: float = SIMILAR_CUTOFF) -> bool:
    """Dua nama BEDA kunci tapi ejaannya hampir sama (salah ketik), mis. "Operator Cuting" ≈ "operator cutting".

    Nama pendek (< 4 huruf) tidak dibandingkan supaya "HR" dan "HRD" tidak saling memperingatkan.
    """
    import difflib
    ka, kb = ref_key(a), ref_key(b)
    if not ka or not kb or ka == kb or min(len(ka), len(kb)) < 4:
        return False
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= cutoff


async def find_similar_refs(db, coll: str, *, name, name_field: str = "name",
                            exclude_id: str | None = None, id_field: str = "id") -> list[dict]:
    """Baris lain di `coll` yang namanya MIRIP (bukan sama persis menurut `ref_key`) — untuk peringatan, bukan tolak."""
    out = []
    async for d in db[coll].find({}, {"_id": 0}):
        if exclude_id and d.get(id_field) == exclude_id:
            continue
        if similar_ref(name, d.get(name_field)):
            out.append(d)
    return out


async def assert_unique_ref(db, coll: str, *, name, label: str, name_field: str = "name",
                            exclude_id: str | None = None, id_field: str = "id",
                            process_code: str | None = None, scope: dict | None = None,
                            key_fn=None) -> None:
    """Tolak (409) bila master dengan nama setara sudah ada — sebutkan yang sudah ada."""
    dup = await find_duplicate_ref(db, coll, name=name, name_field=name_field, exclude_id=exclude_id,
                                   id_field=id_field, process_code=process_code, scope=scope,
                                   key_fn=key_fn)
    if dup:
        shown = dup.get(name_field) or dup.get("code") or ""
        code = dup.get("code")
        raise HTTPException(
            409, f"{label} '{shown}'" + (f" (kode {code})" if code and code != shown else "")
                 + " sudah ada. Pakai yang sudah ada supaya data tidak tercatat dua kali.")


async def seed_once(db, coll: str, docs: list, *, key: str = "code") -> int:
    """Benih bawaan yang aman bila dua permintaan datang BERSAMAAN.

    `_id` tetap per kode (`seed:<koleksi>:<kode>`), jadi sisipan kedua yang bersamaan ditolak indeks
    `_id` — bukan menjadi baris kembar. (Kategori aset ×2 lahir dari pola lama "hitung 0 lalu sisip
    semua" yang dijalankan dua layar sekaligus.)
    """
    from pymongo.errors import DuplicateKeyError
    n = 0
    for d in docs:
        try:
            await db[coll].insert_one({"_id": f"seed:{coll}:{d[key]}", **d})
            n += 1
        except DuplicateKeyError:
            pass
    return n
