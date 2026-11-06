"""core/catalog_margin.py — **SATU rumus margin katalog marketing** (sesi #37).

═══════════════════════════════════════════════════════════════════════════════
MASALAH NYATA YANG DITUTUP BERKAS INI
═══════════════════════════════════════════════════════════════════════════════
Diukur sebelum sesi ini: `marketing_catalog_items` berisi 78 item dan **tidak
satu pun** punya `margin_pct` tersimpan. Endpoint daftar katalog memang
menghitungnya saat baca, tetapi dengan rumus yang menipu:

    row['margin_pct'] = round((hj - hpp) / hj * 100, 1) if hj > 0 else 0.0

Kalau `hpp` = 0 — dan itu keadaan MAYORITAS item, karena HPP baru lahir setelah
BOM/biaya jahit terisi — rumus itu menghasilkan **100%**. Kalau `harga_jual`
juga 0, hasilnya **0%**. Dua-duanya angka yang terlihat sah, dan dua-duanya
BOHONG: yang benar adalah "belum bisa diukur".

Bahayanya bukan teoretis. Marketing memakai kolom margin untuk memutuskan
diskon dan harga flash sale. Item yang HPP-nya belum diketahui akan tampil
sebagai margin 100% — yaitu item yang paling "aman" didiskon — padahal ia justru
satu-satunya item yang untung-ruginya TIDAK diketahui siapa pun.

═══════════════════════════════════════════════════════════════════════════════
ATURAN
═══════════════════════════════════════════════════════════════════════════════
1. **HPP EFEKTIF** dipilih menurut urutan yang paling dekat dengan biaya nyata:
   WAC aktual FG (`unit_cost`)  →  `hpp` FG (kalkulator, ESTIMASI)  →  `hpp` katalog.
   Sumbernya selalu ikut dilaporkan (`hpp_source_effective` + `hpp_source_label`
   + `hpp_is_estimate`) supaya pembaca laporan tahu angka itu biaya nyata (WAC),
   perkiraan kalkulator, atau ketikan tangan di katalog.
   2026-11-02 (owner No.26a): `hpp_fifo_avg` diganti WAC. WAC tinggal di
   `unit_cost` sehingga tombol "Terapkan HPP per Potong" (menulis `hpp`) tidak bisa
   menimpanya; selama WAC belum ada, HPP kalkulator tampil berlabel "estimasi".
2. **HPP tidak diketahui ⇒ `margin_status='belum_bisa_diukur'`, `margin_pct=None`.**
   BUKAN 0, BUKAN 100. `None` memaksa layar menampilkan lencana, bukan angka.
3. Alasannya ditulis (`margin_reason`) — "belum bisa diukur" tanpa sebab hanya
   memindahkan kebingungan, bukan menyelesaikannya.
"""
from __future__ import annotations

OK = "ok"
UNKNOWN = "belum_bisa_diukur"

# Sumber HPP efektif (2026-11-02, owner No.26a) + label siap tampil.
SRC_WAC = "fg_wac"              # biaya nyata: WAC FG (`unit_cost`, core/fg_cost_layers)
SRC_ESTIMATE = "fg_estimasi"    # `hpp` master FG = kalkulator BOM / R&D (perkiraan)
SRC_CATALOG = "catalog_manual"
SOURCE_LABEL = {
    SRC_WAC: "WAC aktual",
    SRC_ESTIMATE: "estimasi (kalkulator HPP)",
    SRC_CATALOG: "ketikan katalog",
    "none": "belum ada",
}
FG_COST_PROJECTION = {"_id": 0, "id": 1, "hpp": 1, "hpp_source": 1, "unit_cost": 1, "wac_components": 1}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def effective_fg_cost(mat: dict | None) -> dict:
    """HPP efektif satu master FG (fungsi murni; dipakai katalog & Portal Penjualan).

    WAC aktual hanya bila FG sudah dinilai WAC (`wac_components` ada) dan > 0 —
    `unit_cost` FG lama yang kosong/0 tidak dianggap biaya nyata."""
    m = mat or {}
    wac = _f(m.get("unit_cost")) if isinstance(m.get("wac_components"), dict) else 0.0
    if wac > 0:
        src, hpp = SRC_WAC, wac
    elif _f(m.get("hpp")) > 0:
        src, hpp = SRC_ESTIMATE, _f(m.get("hpp"))
    else:
        src, hpp = "", 0.0
    return {"hpp": round(hpp, 2), "source": src, "is_estimate": src == SRC_ESTIMATE,
            "label": SOURCE_LABEL.get(src or "none", src),
            "estimate_from": (m.get("hpp_source") or "") if src == SRC_ESTIMATE else ""}


async def fg_cost_map(db, material_ids: list) -> dict:
    """{material_id: {hpp, source, is_estimate, label}} — satu kueri, bukan N+1."""
    mids = [m for m in set(material_ids or []) if m]
    if not mids:
        return {}
    rows = await db.rahaza_materials.find(
        {"id": {"$in": mids}}, FG_COST_PROJECTION).to_list(len(mids) + 10)
    return {r["id"]: effective_fg_cost(r) for r in rows}


def decorate(row: dict, fg_cost: dict = None) -> dict:
    """Isi `hpp_effective`, `margin`, `margin_pct`, `margin_status`, alasan.

    `fg_cost` = entri dari `fg_cost_map()` untuk FG yang tertaut (boleh None).
    Mengubah `row` di tempat DAN mengembalikannya (dipakai berantai).
    """
    harga_jual = _f(row.get("harga_jual"))
    fg = fg_cost or {}
    hpp = _f(fg.get("hpp"))
    source = fg.get("source") or ""
    if hpp <= 0:
        hpp = _f(row.get("hpp"))
        source = SRC_CATALOG if hpp > 0 else "none"

    row["hpp_effective"] = round(hpp, 2)
    row["hpp_source_effective"] = source
    row["hpp_source_label"] = SOURCE_LABEL.get(source, source)
    row["hpp_is_estimate"] = source == SRC_ESTIMATE

    reasons = []
    if harga_jual <= 0:
        reasons.append("harga jual belum diisi")
    if hpp <= 0:
        if not row.get("fg_material_id"):
            reasons.append("belum tertaut ke Master Produk / FG, jadi HPP tidak "
                           "bisa diambil dari mana pun")
        else:
            reasons.append("FG-nya belum punya HPP — BOM atau biaya jahit "
                           "(SPK) belum tercatat")

    if reasons:
        row["margin"] = None
        row["margin_pct"] = None
        row["margin_status"] = UNKNOWN
        row["margin_reason"] = ("Belum bisa diukur: " + "; ".join(reasons) + ".")
    else:
        # 2026-11-06 (Tahap 2): satu rumus margin (atas harga jual) — `core.margin`
        from core import margin as _margin
        m = _margin.margin_of(harga_jual, hpp, nd=1)
        row["margin"] = m["margin"]
        row["margin_pct"] = m["margin_pct"]
        row["margin_status"] = OK
        row["margin_reason"] = ""
    return row


# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (Tahap 2) — SATU urutan HPP item katalog (tambah dari FG = segarkan)
# ══════════════════════════════════════════════════════════════════════════════
def resolve_catalog_hpp(fg: dict | None, model: dict | None) -> tuple:
    """(hpp, source) untuk cache `hpp` item katalog — dipakai "Tambah dari FG", "Segarkan HPP",
    dan "Segarkan dari master" (dulu tambah mendahulukan model, segarkan mendahulukan FG 'bom').

    Urutan: WAC aktual FG → HPP standar FG (HPP per potong per warna/ukuran yang diterapkan) →
    HPP model (rata-rata / R&D / manual, hanya bila FG belum punya angka) → 0."""
    eff = effective_fg_cost(fg)
    if eff["source"] == SRC_WAC:
        return eff["hpp"], "wac"
    if eff["source"] == SRC_ESTIMATE:
        return eff["hpp"], (fg or {}).get("hpp_source") or "fg"
    if model:
        from core import product_master as _pm
        hpp, src = _pm.resolve_hpp(model)
        if hpp:
            return float(hpp), src
    return 0.0, "none"


def summarize(rows: list) -> dict:
    """Ringkas kesehatan margin SELURUH katalog (bukan halaman yang tampil)."""
    measurable = [r for r in rows if r.get("margin_status") == OK]
    unknown = [r for r in rows if r.get("margin_status") == UNKNOWN]
    avg = (round(sum(_f(r.get("margin_pct")) for r in measurable) / len(measurable), 1)
           if measurable else None)
    return {
        "measurable": len(measurable),
        "unmeasurable": len(unknown),
        "avg_margin_pct": avg,
        "hpp_sources": {
            s: sum(1 for r in rows if r.get("hpp_source_effective") == s)
            for s in sorted({r.get("hpp_source_effective") or "none" for r in rows})
        },
        "note": ("Item tanpa HPP dilaporkan sebagai 'belum bisa diukur' dan TIDAK "
                 "ikut menghitung rata-rata margin — memasukkannya sebagai 0% atau "
                 "100% akan membuat rata-rata katalog menyesatkan."),
    }
