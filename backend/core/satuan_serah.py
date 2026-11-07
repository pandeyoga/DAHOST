"""core.satuan_serah — SATUAN SERAH aksesoris & rencana aksesoris PO (Tahap 9, keputusan owner no. 3).

Keputusan owner 7 Nov 2026:
  * aksesoris diatur di PO dengan SATUAN SERAH (mis. "roll isi 2.240 cm", "bungkus isi 1.440 pcs");
  * angka BOM hanya PERKIRAAN (pratinjau) — jumlah FINAL diisi user;
  * stok berkurang sebesar yang benar-benar diserahkan: qty serah × isi kemasan, dalam satuan dasar.

Satuan serah dibaca dari daftar satuan material (`core.uom`), TIDAK mengubah master:
  1. satuan pakai bawaan (`issue_uom`) bila itu kemasan (isi > 1 satuan dasar);
  2. kalau tidak, kemasan TERKECIL di atas satuan dasar (kemasan tingkat 1: roll / bungkus / pack);
  3. kalau material tidak punya kemasan → satuan dasarnya sendiri.

Status satuan serah (dibaca laporan `2026_11_07_cek_satuan_serah.py` dan layar):
  * ``ok``                — kemasan jelas;
  * ``dasar``             — tanpa kemasan, satuan dasar berupa hitungan (pcs, pack, set) — wajar;
  * ``tanpa_kemasan``     — tanpa kemasan padahal satuan dasarnya ukuran (cm, m, gram, kg) → gudang perlu
                            menambah kemasan (roll/bungkus) supaya serah tidak diketik dalam cm;
  * ``kemasan_ganda``     — lebih dari satu kemasan dan tidak ada yang ditandai satuan pakai;
  * ``gross_tidak_baku``  — kemasan bernama "gross" dengan isi selain 144.

Kontrak baris `po_accessories` (dibaca agen po & hpp — NAMA FIELD JANGAN DIUBAH):
  usage_unit · bom_qty_base · handover_uom · handover_factor · bom_qty_handover · plan_qty_handover · source
  (`bom` | `tambahan`). Field lama tetap: accessory_id/name/code, qty_needed (= rencana dalam satuan dasar),
  unit (= satuan dasar), notes, ownership.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from core import uom as uom_core

SOURCE_BOM = "bom"
SOURCE_TAMBAHAN = "tambahan"
# asal baris otomatis (dipakai mesin explode untuk menghapus & menulis ulang barisnya sendiri)
ORIGIN_BOM_INTERNAL = "bom_auto"
ORIGIN_BOM_MAKLON = "bom_maklon_auto"
LEGACY_AUTO_SOURCES = (ORIGIN_BOM_INTERNAL, ORIGIN_BOM_MAKLON)

GROSS_HINTS = ("gross", "gros", "grs")
GROSS_FACTOR = 144.0
MEASURE_UNITS = {"cm", "mm", "m", "meter", "mtr", "yard", "yd", "inch", "gram", "g", "gr", "kg", "ml",
                 "liter", "ltr", "m2", "cm2"}
STATUS_LABEL = {
    "ok": "Kemasan jelas",
    "dasar": "Diserahkan dalam satuan dasar",
    "tanpa_kemasan": "Belum ada kemasan (satuan dasar berupa ukuran)",
    "kemasan_ganda": "Lebih dari satu kemasan, belum ada yang ditandai satuan pakai",
    "gross_tidak_baku": "Satuan \"gross\" tidak berisi 144",
}
_EPS = 1e-9


def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x else 0.0


def fmt_num(v: Any) -> str:
    """Angka gaya Indonesia: 2240 → "2.240", 0.5 → "0,5"."""
    x = _f(v)
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}".replace(",", ".")
    s = f"{x:,.4f}".rstrip("0").rstrip(".")
    return s.replace(",", "~").replace(".", ",").replace("~", ".")


def _is_gross(row: dict) -> bool:
    blob = f"{row.get('code') or ''} {row.get('name') or ''}".strip().lower()
    return any(h in blob.split() or blob.startswith(h) for h in GROSS_HINTS)


def packaging_rows(material: Optional[dict]) -> list:
    """Kemasan di ATAS satuan dasar (isi > 1), urut dari yang terkecil."""
    return [r for r in uom_core.resolve_uoms(material) if not r.get("is_base") and _f(r.get("factor")) > 1 + _EPS]


def _row_name(row: dict) -> str:
    name = (row.get("name") or "").strip()
    code = (row.get("code") or "").strip()
    return (name if name and name.upper() != code.upper() else code).lower() or code.lower()


def unit_label(material: Optional[dict], code: Any, factor: Any = None) -> str:
    """Label satuan serah untuk layar & dokumen: "roll isi 2.240 cm" / "pcs"."""
    base = uom_core.base_uom_of(material)
    c = uom_core.normalize_code(code) or base
    row = uom_core.find_uom(material, c) or {"code": c, "name": c}
    f = _f(factor) if factor not in (None, "") else _f(row.get("factor") or 1)
    if c == base or abs(f - 1) < _EPS:
        return _row_name(row) or base
    return f"{_row_name(row)} isi {fmt_num(f)} {base}"


def handover_unit(material: Optional[dict]) -> dict:
    """Satuan serah sebuah material. Return {uom, factor, label, status, note, base_uom, options}."""
    m = material or {}
    base = uom_core.base_uom_of(m)
    packs = packaging_rows(m)
    issue = uom_core.issue_uom_of(m)
    chosen = next((p for p in packs if p["code"] == issue), None)
    status, note = "ok", ""
    if chosen is None and packs:
        chosen = packs[0]
        if len(packs) > 1:
            status = "kemasan_ganda"
            note = (f"Ada {len(packs)} kemasan ({', '.join(p['code'] for p in packs)}); dipakai yang terkecil "
                    f"({packs[0]['code']}). Tandai satuan pakai di master bila yang diserahkan berbeda.")
    if chosen is None:
        chosen = {"code": base, "name": base, "factor": 1.0}
        if base in MEASURE_UNITS:
            status = "tanpa_kemasan"
            note = f"Belum ada kemasan — diserahkan dalam {base}. Tambahkan kemasan (mis. roll) di master material."
        else:
            status = "dasar"
    if _is_gross(chosen) and abs(_f(chosen.get("factor")) - GROSS_FACTOR) > _EPS:
        status = "gross_tidak_baku"
        if chosen.get("code") == base:
            note = ("Satuan dasar bernama \"gross\" — periksa apakah stok & BOM memang dihitung per gross (isi 144) "
                    "atau sebenarnya per pcs / kemasan lain.")
        else:
            note = (f"Kemasan \"{chosen.get('name') or chosen.get('code')}\" berisi {fmt_num(chosen.get('factor'))} {base}, "
                    f"bukan 144. Periksa isi kemasan di master material.")
    factor = _f(chosen.get("factor")) or 1.0
    options = [{"uom": r["code"], "factor": _f(r["factor"]) or 1.0, "label": unit_label(m, r["code"], r["factor"])}
               for r in uom_core.resolve_uoms(m) if _f(r.get("factor")) >= 1 - _EPS]
    return {"uom": chosen["code"], "factor": factor, "label": unit_label(m, chosen["code"], factor),
            "status": status, "status_label": STATUS_LABEL.get(status, status), "note": note,
            "base_uom": base, "options": options}


def resolve_handover(material: Optional[dict], uom: Any = None) -> dict:
    """Satuan serah yang DIPILIH user (bila sah untuk material ini) atau bawaannya."""
    hu = handover_unit(material)
    code = uom_core.normalize_code(uom)
    if code and code != hu["uom"]:
        row = uom_core.find_uom(material, code)
        if row and _f(row.get("factor")) > 0:
            f = _f(row["factor"])
            return {**hu, "uom": row["code"], "factor": f, "label": unit_label(material, row["code"], f)}
    return hu


def ceil_units(qty_base: Any, factor: Any) -> float:
    """Perkiraan BOM dibulatkan KE ATAS ke satuan serah (2,3 roll → 3 roll)."""
    q, f = _f(qty_base), _f(factor) or 1.0
    if q <= _EPS:
        return 0
    return int(math.ceil(q / f - 1e-9))


def to_base(qty_handover: Any, factor: Any) -> float:
    """Qty serah → satuan dasar (yang memotong stok)."""
    return round(_f(qty_handover) * (_f(factor) or 1.0), 6)


def is_auto_row(row: dict) -> bool:
    """Baris rencana yang ditulis mesin BOM (baru: source='bom'; lama: source bom_auto/bom_maklon_auto)."""
    return (row.get("source") in (SOURCE_BOM,) + LEGACY_AUTO_SOURCES) or bool(row.get("bom_origin"))


def plan_fields(material: Optional[dict], *, bom_qty_base: Any = 0, source: str = SOURCE_BOM,
                plan_qty_handover: Any = None, handover_uom: Any = None, usage_unit: str = "") -> dict:
    """Field kontrak satu baris `po_accessories` (dipakai SEMUA penulis baris itu).

    `plan_qty_handover=None` → bawaan = perkiraan BOM (dibulatkan ke atas ke satuan serah).
    `qty_needed` (field lama, dibaca pengadaan & penjaga lebih-keluar) = rencana × isi kemasan."""
    hu = resolve_handover(material, handover_uom)
    est_base = round(_f(bom_qty_base), 6) if source == SOURCE_BOM else 0.0
    est_hand = ceil_units(est_base, hu["factor"]) if source == SOURCE_BOM else 0
    plan = est_hand if plan_qty_handover in (None, "") else round(max(0.0, _f(plan_qty_handover)), 4)
    base_unit = uom_core.base_uom_of(material) if material else (uom_core.normalize_code(usage_unit) or "pcs")
    return {
        "usage_unit": base_unit,
        "bom_qty_base": est_base,
        "handover_uom": hu["uom"],
        "handover_factor": hu["factor"],
        "handover_label": hu["label"],
        "handover_status": hu["status"],
        "bom_qty_handover": est_hand,
        "plan_qty_handover": plan,
        "source": source if source in (SOURCE_BOM, SOURCE_TAMBAHAN) else SOURCE_TAMBAHAN,
        "qty_needed": round(to_base(plan, hu["factor"]), 4),
        "unit": base_unit,
    }


def row_key(row: dict) -> str:
    """Kunci satu aksesoris lintas PO / kiriman / MI: id master, lalu kode, lalu nama."""
    return str(row.get("accessory_id") or row.get("material_id") or (row.get("accessory_code") or row.get("code")
               or row.get("accessory_name") or row.get("name") or "")).strip().lower()


def carry_plan(new_rows: list, old_rows: list) -> list:
    """Rencana yang SUDAH DIUBAH user (≠ perkiraan lama) dipertahankan saat BOM dihitung ulang.

    Rencana yang masih sama dengan perkiraan lama ikut perkiraan baru (qty PO berubah → rencana ikut)."""
    old = {}
    for r in old_rows or []:
        if r.get("plan_qty_handover") in (None, ""):
            continue
        old[row_key(r)] = r
    for r in new_rows:
        prev = old.get(row_key(r))
        if not prev:
            continue
        edited = abs(_f(prev.get("plan_qty_handover")) - _f(prev.get("bom_qty_handover"))) > _EPS
        same_unit = (prev.get("handover_uom") or "") == (r.get("handover_uom") or "")
        if edited and same_unit:
            r["plan_qty_handover"] = _f(prev["plan_qty_handover"])
            r["qty_needed"] = round(to_base(r["plan_qty_handover"], r.get("handover_factor")), 4)
            r["plan_edited"] = True
    return new_rows
