"""core.cutting_lines — SATU ORDER CUTTING: BANYAK KAIN (GULUNGAN) × BANYAK HASIL POTONGAN.

Keputusan owner 10 Nov 2026 ("cutting bisa lebih dari satu", "roll kain juga bisa lebih dari satu, model lebih dari
satu"):
  * `inputs[]`  — baris masukan: kain dari master + gulungan yang dipilih (boleh beberapa kain, tiap kain beberapa
                  gulungan). Pemakaian, sisa, limbah, dan pemakaian per gulungan dicatat PER KAIN.
  * `outputs[]` — baris hasil: model × varian (warna · ukuran · SKU) × target pcs (+ baris PO opsional). Tiap baris
                  punya master potongannya sendiri (`CUT-<MODEL>-<WARNA>-<UKURAN>`) dan `roll_ids` = gulungan yang
                  dipakai untuk hasil itu. Tautan gulungan → hasil adalah KETELUSURAN ("roll ini dipakai buat potongan
                  apa"), BUKAN dasar HPP.
  * HPP potongan per pcs = Σ(kain terpakai × harga satuan kain itu) ÷ total pcs hasil SEMUA baris — sama untuk semua
    baris order itu ("konsisten saja ... tinggal dibagi"). Order satu-baris menghasilkan angka yang sama dengan rumus
    lama (nilai kain ÷ pcs).

Dokumen LAMA (satu kain · satu hasil, field di tingkat atas) TIDAK dimigrasi paksa: `inputs_of` / `outputs_of`
menormalkannya saat dibaca menjadi `inputs[0]` / `outputs[0]`. Sebaliknya field lama tingkat atas tetap DIISI
(`compat_fields`) supaya pembaca lama tetap benar untuk order satu baris. Untuk order banyak baris, id tingkat atas
hanya diisi bila SEMUA baris sama (mis. satu model tiga ukuran → `model_id` tetap terisi); teksnya digabung untuk
tampilan & pencarian. Pembaca yang mencari order lewat id (pemakaian master, kesehatan potongan, kebutuhan PO) kini
juga mencari di `inputs.*` / `outputs.*` — lihat `query_any`.

Modul ini MURNI (tanpa DB).
"""
from __future__ import annotations

import copy

INPUT_FIELDS = ("input_material_id", "input_material_code", "input_material_name", "input_unit", "input_color",
                "input_unit_cost", "planned_input_qty", "consumed_input_qty", "waste_qty", "leftover_qty",
                "roll_ids", "roll_required", "stock_at_create", "stock_total_at_create")
INPUT_NUM = ("input_unit_cost", "planned_input_qty", "consumed_input_qty", "waste_qty", "leftover_qty")
INPUT_SUMS = ("planned_input_qty", "consumed_input_qty", "waste_qty", "leftover_qty")

IDENTITY_IDS = ("model_id", "variant_id", "size_id", "color_id", "output_material_id", "po_item_id", "po_id")
IDENTITY_TEXT = ("style_sku", "style_name", "model_code", "model_name", "variant_sku", "output_color", "output_size",
                 "output_material_code", "output_material_name", "po_number")
OUTPUT_NUM = ("planned_output_qty", "produced_qty", "output_unit_cost")


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _unit(v) -> str:
    return str(v or "").strip().lower()


# ─────────────────────────────── normalisasi baca ───────────────────────────────
def inputs_of(order: dict) -> list[dict]:
    """Baris kain order (dokumen lama → satu baris `in-1` dari field tingkat atas)."""
    rows = (order or {}).get("inputs")
    if isinstance(rows, list) and rows:
        out = []
        for i, r in enumerate(rows):
            x = copy.deepcopy(r or {})
            x["line_id"] = x.get("line_id") or f"in-{i + 1}"
            x["roll_ids"] = [dict(rr) for rr in (x.get("roll_ids") or []) if isinstance(rr, dict)]
            for k in INPUT_NUM:
                x[k] = _f(x.get(k))
            x["roll_required"] = bool(x.get("roll_required"))
            out.append(x)
        return out
    if not (order or {}).get("input_material_id"):
        return []
    x = {"line_id": "in-1"}
    for k in INPUT_FIELDS:
        x[k] = copy.deepcopy(order.get(k))
    x["roll_ids"] = [dict(rr) for rr in (order.get("roll_ids") or []) if isinstance(rr, dict)]
    for k in INPUT_NUM:
        x[k] = _f(x.get(k))
    x["roll_required"] = bool(x.get("roll_required"))
    return [x]


def outputs_of(order: dict) -> list[dict]:
    """Baris hasil order (dokumen lama → satu baris `out-1`; gulungan order = gulungan hasil itu)."""
    rows = (order or {}).get("outputs")
    if isinstance(rows, list) and rows:
        out = []
        for i, r in enumerate(rows):
            x = copy.deepcopy(r or {})
            x["line_id"] = x.get("line_id") or f"out-{i + 1}"
            x["roll_ids"] = [str(v) for v in (x.get("roll_ids") or []) if v]
            for k in OUTPUT_NUM:
                x[k] = _f(x.get(k))
            out.append(x)
        return out
    o = order or {}
    if not any(k in o for k in ("model_id", "output_material_id", "style_name", "input_material_id",
                                "planned_output_qty", "produced_qty")):
        return []
    x = {"line_id": "out-1"}
    for k in IDENTITY_IDS + IDENTITY_TEXT:
        x[k] = o.get(k) or ""
    x["output_from_bom"] = bool(o.get("output_from_bom"))
    for k in OUTPUT_NUM:
        x[k] = _f(o.get(k))
    x["roll_ids"] = [r.get("roll_id") for r in (o.get("roll_ids") or []) if isinstance(r, dict) and r.get("roll_id")]
    return [x]


def output_label(o: dict) -> str:
    """"Model · warna · ukuran · SKU" — label satu baris hasil untuk layar & catatan gulungan."""
    bits = [o.get("style_name") or o.get("model_name") or o.get("model_code") or "Hasil",
            o.get("output_color") or "", o.get("output_size") or "", o.get("variant_sku") or ""]
    return " · ".join(b for b in bits if b)


def input_label(i: dict) -> str:
    return f"{i.get('input_material_code') or ''} — {i.get('input_material_name') or ''}".strip(" —") or "kain"


# ─────────────────────────────── tulis: field kompatibel ───────────────────────────────
def _common(rows: list[dict], key: str) -> str:
    vals = {str(r.get(key) or "") for r in rows}
    return vals.pop() if len(vals) == 1 else ""


def _joined(rows: list[dict], key: str) -> str:
    seen: list[str] = []
    for r in rows:
        v = str(r.get(key) or "").strip()
        if v and v not in seen:
            seen.append(v)
    return ", ".join(seen)


def unit_totals(inputs: list[dict]) -> list[dict]:
    """Kain per SATUAN (kg, yard, meter tidak pernah dijumlah jadi satu angka) — dibaca dashboard."""
    acc: dict = {}
    for r in inputs or []:
        u = _unit(r.get("input_unit")) or "-"
        x = acc.setdefault(u, {"unit": u, "planned": 0.0, "consumed": 0.0, "waste": 0.0})
        x["planned"] += _f(r.get("planned_input_qty"))
        x["consumed"] += _f(r.get("consumed_input_qty"))
        x["waste"] += _f(r.get("waste_qty"))
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in acc.values()]


def compat_fields(inputs: list[dict], outputs: list[dict]) -> dict:
    """Field tingkat atas yang dibaca modul lama, dihitung dari baris (order satu baris = persis seperti dulu)."""
    out: dict = {}
    units: list[str] = []
    for r in inputs:
        u = _unit(r.get("input_unit"))
        if u not in units:
            units.append(u)
    if len(inputs) == 1:
        for k in INPUT_FIELDS:
            out[k] = copy.deepcopy(inputs[0].get(k))
        for k in INPUT_NUM:
            out[k] = round(_f(out.get(k)), 4)
        out["roll_ids"] = [dict(rr) for rr in inputs[0].get("roll_ids") or []]
        out["roll_required"] = bool(inputs[0].get("roll_required"))
    else:
        same = len(units) == 1
        out["input_material_id"] = _common(inputs, "input_material_id")
        for k in ("input_material_code", "input_material_name", "input_color"):
            out[k] = _joined(inputs, k)
        out["input_unit"] = units[0] if same else ""
        for k in INPUT_SUMS:
            out[k] = round(sum(_f(r.get(k)) for r in inputs), 4) if same else 0.0
        out["input_unit_cost"] = 0.0
        out["roll_ids"] = [{**rr, "input_material_id": r.get("input_material_id")}
                           for r in inputs for rr in (r.get("roll_ids") or [])]
        out["roll_required"] = any(bool(r.get("roll_required")) for r in inputs)
    out["input_units_mixed"] = len(units) > 1
    out["unit_totals"] = unit_totals(inputs)
    if len(outputs) == 1:
        for k in IDENTITY_IDS + IDENTITY_TEXT:
            out[k] = outputs[0].get(k) or ""
        out["output_from_bom"] = bool(outputs[0].get("output_from_bom"))
    else:
        for k in IDENTITY_IDS:
            out[k] = _common(outputs, k)
        for k in IDENTITY_TEXT:
            out[k] = _joined(outputs, k)
        out["output_from_bom"] = bool(outputs) and all(bool(o.get("output_from_bom")) for o in outputs)
    out["planned_output_qty"] = round(sum(_f(o.get("planned_output_qty")) for o in outputs), 4)
    out["produced_qty"] = round(sum(_f(o.get("produced_qty")) for o in outputs), 4)
    out["line_counts"] = {"inputs": len(inputs), "outputs": len(outputs)}
    out["multi"] = len(inputs) > 1 or len(outputs) > 1
    return out


def query_any(field_top: str, field_line: str, value) -> dict:
    """Kueri order yang menyebut `value` di field lama tingkat atas ATAU di salah satu baris."""
    return {"$or": [{field_top: value}, {field_line: value}]}


# ─────────────────────────────── ketelusuran gulungan → hasil ───────────────────────────────
def roll_usage(order: dict) -> list[dict]:
    """Tabel "gulungan → hasil potongan": no. roll, kain, lot warna, terpakai → model/varian (pcs)."""
    ins, outs = inputs_of(order), outputs_of(order)
    rows = []
    for i in ins:
        for r in i.get("roll_ids") or []:
            rid = r.get("roll_id")
            used_for = [o for o in outs if rid and rid in (o.get("roll_ids") or [])]
            rows.append({
                "roll_id": rid, "roll_no": r.get("roll_no") or "", "color_lot": r.get("color_lot") or "",
                "uom": r.get("uom") or i.get("input_unit") or "",
                "consumed_qty": round(_f(r.get("consumed_qty")), 3), "remaining": round(_f(r.get("remaining")), 3),
                "input_line_id": i.get("line_id"), "material_id": i.get("input_material_id"),
                "material_code": i.get("input_material_code") or "", "material_name": i.get("input_material_name") or "",
                "outputs": [{"line_id": o.get("line_id"), "label": output_label(o),
                             "output_material_code": o.get("output_material_code") or "",
                             "planned_output_qty": _f(o.get("planned_output_qty")),
                             "produced_qty": _f(o.get("produced_qty"))} for o in used_for],
            })
    return rows


def roll_usage_text(row: dict) -> str:
    """Kalimat "dipakai untuk: Model A · Merah · M (40 pcs), …" untuk satu gulungan."""
    bits = [f"{o['label']} ({o['produced_qty']:g} pcs)" if o.get("produced_qty") else o["label"]
            for o in row.get("outputs") or []]
    return ", ".join(bits) if bits else "belum ditautkan ke hasil potongan"


# ─────────────────────────────── kain terpakai untuk satu PO ───────────────────────────────
def fabric_used_for_po(order: dict, po_id: str) -> dict:
    """Kain terpakai order ini yang menjadi bagian PO `po_id` → {material_id: qty}.

    Satu baris hasil (dulu satu-satunya bentuk): seluruh kain milik PO baris itu — angka sama dengan dulu.
    Banyak baris: dibagi menurut pcs hasil baris yang tertaut ke PO itu ÷ total pcs hasil (aturan HPP yang sama:
    biaya kain dibagi rata per pcs). Belum ada hasil → menurut target pcs."""
    ins, outs = inputs_of(order), outputs_of(order)
    if not po_id or not ins or not outs:
        return {}
    basis = "produced_qty" if sum(_f(o.get("produced_qty")) for o in outs) > 0 else "planned_output_qty"
    total = sum(_f(o.get(basis)) for o in outs)
    linked = sum(_f(o.get(basis)) for o in outs if (o.get("po_id") or "") == po_id)
    if len(outs) == 1:
        share = 1.0 if (outs[0].get("po_id") or order.get("po_id") or "") == po_id else 0.0
    else:
        share = (linked / total) if total > 0 else 0.0
    out: dict = {}
    for i in ins:
        mid = i.get("input_material_id")
        if mid and share > 0:
            out[mid] = out.get(mid, 0.0) + _f(i.get("consumed_input_qty")) * share
    return {k: round(v, 4) for k, v in out.items()}


def cost_per_pcs(total_cost: float, total_pcs: float) -> float:
    """HPP potongan per pcs order = total biaya kain ÷ total pcs hasil SEMUA baris (sama untuk semua baris)."""
    return round(_f(total_cost) / _f(total_pcs), 2) if _f(total_pcs) > 0 else 0.0
