"""core.bom_fill — importir sheet BOM_AKSESORIS versi 3 (diperkeras, 2026-09-17).

Aturan berkas:
- Baris ber-`kode_model` = awal KELOMPOK; baris di bawahnya yang `kode_model`-nya kosong = bahan lain kelompok yang sama.
- Kolom `varian` = daftar warna/ukuran (pisah koma) yang memakai bahan kelompok ini. Kosong = semua varian,
  TETAPI hanya bila model itu punya SATU kelompok. Model banyak-kelompok tanpa `varian` → kelompok DILEWATI + dilaporkan.
  TIDAK ADA tebakan warna dari nama material.
- `qty_per_pcs` boleh berisi satuan ("60 cm", "1 pcs"); satuan juga bisa di kolom `satuan`. Satuan dinormalisasi
  (Meter/m/M→m, cm→m, Roll/TRL→roll, Pack/Bks→pack, Pcs/PCS→pcs, Gross). Satuan tak dikenal (F, botol) → ditolak.
  pcs→roll/pack hanya lewat `pack_size` master; tanpa itu → dilewati + dilaporkan.
- Semantik TERAPKAN = GANTI UTUH: baris aksesoris BOM tiap (model, varian) yang disebut berkas diganti seluruhnya
  oleh isi berkas (kain & potongan dipertahankan). Model/varian yang tidak disebut berkas tidak disentuh. Idempoten.
"""
from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime, timezone

from core import bom_uom

_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_ZW[0xA0] = 0x20
_QTY_RE = re.compile(r"^\s*([\d.,]+)\s*([a-zA-Z]*)\s*$")
_SPLIT_RE = re.compile(r"[,;/|\n]+")
_COUNT_UNITS = {"pcs"}
UNIT_ALIAS = {
    "m": "m", "meter": "m", "mtr": "m", "mt": "m", "metre": "m", "cm": "cm", "mm": "mm", "yard": "yard", "yd": "yard",
    "roll": "roll", "rol": "roll", "trl": "roll", "gulung": "roll",
    "pack": "pack", "pak": "pack", "bks": "pack", "bungkus": "pack",
    "pcs": "pcs", "pc": "pcs", "buah": "pcs", "biji": "pcs", "lembar": "pcs", "unit": "pcs",
    "gross": "gross", "grs": "gross", "lusin": "lusin", "dz": "lusin", "dozen": "lusin",
    "kg": "kg", "gram": "gram", "gr": "gram", "g": "gram",
}
CATEGORIES = {
    "model_tanpa_sku": "Model belum punya varian/SKU",
    "model_dihentikan": "Model dihentikan (semua SKU 'sudah tidak dijual')",
    "kelompok_tanpa_varian": "Kelompok tanpa kolom varian (model banyak kelompok)",
    "satuan_tak_valid": "Satuan tidak valid / tidak bisa dikonversi",
    "kode_tak_dikenal": "Kode material tidak dikenal",
    "qty_kosong": "qty_per_pcs kosong / bukan angka",
    "warna_tak_dikenal": "Warna/ukuran di kolom varian tidak dikenal",
    "model_tak_dikenal": "Kode model tidak ada",
    "baris_tanpa_model": "Baris tanpa kode_model di atasnya",
}


def _now():
    return datetime.now(timezone.utc)


def clean(v) -> str:
    if v in (None, ""):
        return ""
    return str(v).translate(_ZW).strip()


def _num(v) -> float:
    s = clean(v).replace(" ", "")
    if s.count(".") > 1 or (s.count(".") == 1 and "," in s):
        s = s.replace(".", "")
    return float(s.replace(",", ".") or 0)


def norm_unit(u) -> str | None:
    """Satuan tertulis → satuan kanonik; None bila tidak dikenal (mis. 'F', 'botol')."""
    s = clean(u).lower().rstrip(".")
    if not s:
        return ""
    return UNIT_ALIAS.get(s)


def parse_qty(v) -> tuple[float, str]:
    """"60 cm" → (60.0, "cm"); 3 → (3.0, ""). ValueError bila kosong/bukan angka."""
    if isinstance(v, (int, float)):
        return float(v), ""
    m = _QTY_RE.match(clean(v))
    if not m:
        raise ValueError(f"qty '{clean(v)}' kosong/tidak dikenali (contoh: 60 cm, 1 pcs, 0,5)")
    return _num(m.group(1)), m.group(2)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", clean(s).lower())


def unit_factor(mat: dict, unit: str) -> tuple[float, str, str, str]:
    """(faktor→dasar, satuan_dasar, status, catatan). pcs→kemasan hanya lewat pack_size master."""
    f, base, st, note = bom_uom.line_factor(mat, unit)
    base = bom_uom.norm_unit(base)
    if st != "mismatch":
        return f, base, st, note
    pack = float(mat.get("pack_size") or 0)
    if unit in _COUNT_UNITS and base in bom_uom.PACKAGING_UNITS:
        if pack > 1:
            return 1.0 / pack, base, "pack", f"1 {base} = {pack:g} pcs (isi kemasan master)"
        return 1.0, base, "mismatch", f"satuan dasar '{base}' tetapi isi_per_satuan_beli (pcs per {base}) belum ada di master — isi lewat sheet MATERIAL"
    return 1.0, base, "mismatch", f"satuan '{unit}' tidak bisa dikonversi ke satuan dasar '{base}'"


def pcs_uom_row(mat: dict) -> dict | None:
    pack = float(mat.get("pack_size") or 0)
    base = bom_uom.norm_unit(mat.get("base_uom") or mat.get("unit"))
    if base in bom_uom.PACKAGING_UNITS and pack > 1 and not any(bom_uom.norm_unit(u.get("code")) in _COUNT_UNITS for u in mat.get("uoms") or []):
        return {"code": "pcs", "name": "PCS", "factor": round(1.0 / pack, 8), "is_base": False, "level": 1, "parent": base, "notes": f"1 {base} = {pack:g} pcs"}
    return None


def match_tokens(tokens: list[str], variants: list[dict]) -> tuple[set, set, list]:
    """Token varian → (color_codes, size_codes, unmatched). Cocok lewat kode/nama, fuzzy ≥ 0.8 hanya untuk typo."""
    color_by_norm: dict[str, str] = {}
    size_by_norm: dict[str, str] = {}
    for v in variants:
        cc = (v.get("color_code") or "").upper()
        if cc:
            color_by_norm[_norm(cc)] = cc
            color_by_norm[_norm(v.get("color_name") or "")] = cc
        sc = (v.get("size_code") or "").upper()
        if sc:
            size_by_norm[_norm(sc)] = sc
    color_by_norm.pop("", None)
    size_by_norm.pop("", None)
    colors, sizes, unmatched = set(), set(), []
    for tok in tokens:
        n = _norm(tok)
        if not n:
            continue
        if n in size_by_norm:
            sizes.add(size_by_norm[n])
        elif n in color_by_norm:
            colors.add(color_by_norm[n])
        else:
            close = difflib.get_close_matches(n, [k for k in color_by_norm if len(k) >= 3], n=1, cutoff=0.8)
            if close:
                colors.add(color_by_norm[close[0]])
            else:
                unmatched.append(tok.strip())
    return colors, sizes, unmatched


def _variants_label(variants: list[dict]) -> str:
    colors = sorted({(v.get("color_name") or v.get("color_code") or "") for v in variants})
    sizes = sorted({v.get("size_code") or "" for v in variants})
    return f"Warna: {', '.join(c for c in colors if c)} · Ukuran: {', '.join(s for s in sizes if s)}"


async def load_model_variants(db, model_ids: list[str]) -> dict:
    out: dict = {}
    async for v in db.rahaza_model_variants.find({"model_id": {"$in": model_ids}, "active": True},
                                                 {"_id": 0, "id": 1, "model_id": 1, "sku": 1, "color_code": 1, "color_name": 1, "size_id": 1, "size_code": 1}):
        out.setdefault(v["model_id"], []).append(v)
    return out


def _issue(issues: list, kategori: str, row: int, detail: str, **extra) -> None:
    issues.append({"kategori": kategori, "row": row, "detail": detail, **extra})


def issue_text(i: dict) -> str:
    who = " ".join(x for x in (i.get("model_code"), i.get("code")) if x)
    return f"BOM_AKSESORIS baris {i['row']}: {who + ' — ' if who else ''}{i['detail']}"


# ═══════════════════════════════════════════════════════════════════════════
# PARSE
# ═══════════════════════════════════════════════════════════════════════════
async def parse_bom_sheet(db, ws, models: dict) -> dict:
    """models = {kode_model: {id, code, name}} → {bom_groups, bom_lines, bom_issues, bom_warnings}."""
    mat_master = {m["code"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}, "active": {"$ne": False}}, {"_id": 0}).to_list(30000)}
    rows = list(ws.iter_rows(values_only=True, min_row=2))
    groups: list[dict] = []
    issues: list[dict] = []
    cur: dict | None = None
    for i, r in enumerate(rows, start=2):
        r = tuple(r) + (None,) * (8 - len(r))
        mcode, matcode = clean(r[0]).upper(), clean(r[2]).upper()
        if not mcode and not matcode:
            continue
        if mcode:
            if mcode not in models:
                _issue(issues, "model_tak_dikenal", i, "kode model tidak ada di master — kelompok dilewati", model_code=mcode, model_name=clean(r[1]))
                cur = None
                continue
            cur = {"row": i, "model_code": mcode, "model_id": models[mcode]["id"], "model_name": models[mcode].get("name"),
                   "varian_raw": clean(r[7]), "lines": [], "targets": None, "target_label": "", "note": ""}
            groups.append(cur)
        if cur is None:
            _issue(issues, "baris_tanpa_model", i, "tidak ada kode_model di atasnya — baris dilewati", code=matcode, name=clean(r[3]))
            continue
        if not matcode:
            continue  # baris placeholder template
        ctx = {"model_code": cur["model_code"], "model_name": cur["model_name"], "code": matcode, "name": clean(r[3]), "qty_raw": clean(r[4]), "unit_raw": clean(r[5])}
        mat = mat_master.get(matcode)
        if not mat:
            close = difflib.get_close_matches(matcode, list(mat_master), n=1, cutoff=0.85)
            _issue(issues, "kode_tak_dikenal", i, "kode material tidak ada di master" + (f" (mirip: {close[0]})" if close else "") + " — baris dilewati", **ctx)
            continue
        try:
            qty, unit_in_qty = parse_qty(r[4])
        except ValueError as e:
            _issue(issues, "qty_kosong", i, f"{e} — baris dilewati", **ctx)
            continue
        if qty <= 0:
            _issue(issues, "qty_kosong", i, "qty_per_pcs wajib > 0 — baris dilewati", **ctx)
            continue
        base = bom_uom.norm_unit(mat.get("base_uom") or mat.get("unit") or "pcs")
        raw_unit = unit_in_qty or clean(r[5])
        unit = norm_unit(raw_unit) if raw_unit else base
        if unit is None:
            _issue(issues, "satuan_tak_valid", i, f"satuan '{raw_unit}' tidak dikenal (pakai m/cm/roll/pack/pcs/gross) — baris dilewati", **ctx)
            continue
        f, base, st, note = unit_factor(mat, unit)
        if st == "mismatch":
            _issue(issues, "satuan_tak_valid", i, f"{note} — baris dilewati", **ctx)
            continue
        cur["lines"].append({"row": i, "code": mat["code"], "material_id": mat["id"], "name": mat["name"], "material_type": mat.get("type"),
                             "qty": qty, "unit": unit, "qty_base": round(qty * f, 6), "unit_base": base, "uom_note": note, "add_pcs_uom": st == "pack",
                             "unit_cost": float(mat.get("unit_cost") or 0)})
    variants_by_model = await load_model_variants(db, list({g["model_id"] for g in groups}))
    stopped = {m["model_id"] for m in await db.rahaza_model_variants.aggregate([
        {"$match": {"model_id": {"$in": list({g["model_id"] for g in groups})}}},
        {"$group": {"_id": "$model_id", "aktif": {"$sum": {"$cond": [{"$ne": ["$active", False]}, 1, 0]}}}},
        {"$match": {"aktif": 0}}, {"$project": {"model_id": "$_id"}}]).to_list(5000)}
    for g in groups:
        if not variants_by_model.get(g["model_id"]):
            if g["model_id"] in stopped:
                _issue(issues, "model_dihentikan", g["row"], "semua SKU model ini sudah dinonaktifkan ('sudah tidak dijual' di HARGA_JUAL_SKU) — BOM tidak diperlukan, kelompok dilewati",
                       model_code=g["model_code"], model_name=g["model_name"], varian_raw=g["varian_raw"])
                continue
            _issue(issues, "model_tanpa_sku", g["row"], "model belum punya varian/SKU (buat dulu di RnD → Master Produk → Varian) — kelompok dilewati",
                   model_code=g["model_code"], model_name=g["model_name"], varian_raw=g["varian_raw"])
    groups = [g for g in groups if g["lines"] and variants_by_model.get(g["model_id"])]
    by_model: dict = {}
    for g in groups:
        by_model.setdefault(g["model_id"], []).append(g)
    kept: list[dict] = []
    for model_id, gs in by_model.items():
        variants = variants_by_model.get(model_id) or []
        for g in gs:
            if g["varian_raw"]:
                tokens = [t for t in _SPLIT_RE.split(g["varian_raw"]) if t.strip()]
                colors, sizes, unmatched = match_tokens(tokens, variants)
                for tok in unmatched:
                    _issue(issues, "warna_tak_dikenal", g["row"], f"varian '{tok}' tidak dikenal ({_variants_label(variants)})"
                           + (" — token lain tetap dipakai" if (colors or sizes) else " — kelompok dilewati"),
                           model_code=g["model_code"], model_name=g["model_name"], token=tok, varian_raw=g["varian_raw"])
                if not colors and not sizes:
                    continue
                g["targets"] = {"colors": sorted(colors), "sizes": sorted(sizes)}
            elif len(gs) > 1:
                mats_txt = "; ".join(ln["name"][:40] for ln in g["lines"][:4])
                _issue(issues, "kelompok_tanpa_varian", g["row"], f"model punya {len(gs)} kelompok tetapi kelompok ini tanpa kolom varian ({mats_txt}) — "
                       f"isi kolom varian ({_variants_label(variants)}) — kelompok dilewati", model_code=g["model_code"], model_name=g["model_name"],
                       materials="; ".join(f"{ln['code']} {ln['name']}" for ln in g["lines"]), varian_tersedia=_variants_label(variants))
                continue
            tv = target_variants(g, variants)
            if not tv:
                _issue(issues, "warna_tak_dikenal", g["row"], f"varian {g['varian_raw']!r} tidak menghasilkan SKU — kelompok dilewati",
                       model_code=g["model_code"], model_name=g["model_name"], token=g["varian_raw"], varian_raw=g["varian_raw"])
                continue
            g["target_skus"] = [v["sku"] for v in tv]
            g["target_label"] = "semua varian" if g["targets"] is None else \
                " · ".join(x for x in (", ".join(g["targets"]["colors"]), ", ".join(g["targets"]["sizes"])) if x)
            kept.append(g)
    flat = [{"row": ln["row"], "model_code": g["model_code"], "model_name": g["model_name"], "target": g["target_label"], "target_skus": len(g["target_skus"]),
             "code": ln["code"], "name": ln["name"], "qty": ln["qty"], "unit": ln["unit"], "qty_base": ln["qty_base"], "unit_base": ln["unit_base"],
             "note": " · ".join(x for x in (ln["uom_note"], "harga material 0 → HPP belum tervalidasi" if ln["unit_cost"] <= 0 else "") if x)}
            for g in kept for ln in g["lines"]]
    counts: dict = {}
    for i in issues:
        counts[i["kategori"]] = counts.get(i["kategori"], 0) + 1
    return {"bom_groups": kept, "bom_lines": flat, "bom_issues": issues, "bom_issue_counts": counts, "bom_warnings": [issue_text(i) for i in issues]}


def target_variants(g: dict, variants: list[dict]) -> list[dict]:
    t = g.get("targets")
    if not t:
        return list(variants)
    out = []
    for v in variants:
        ok_c = not t["colors"] or (v.get("color_code") or "").upper() in t["colors"]
        ok_s = not t["sizes"] or (v.get("size_code") or "").upper() in t["sizes"]
        if ok_c and ok_s:
            out.append(v)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# APPLY — ganti utuh baris aksesoris per (model, varian)
# ═══════════════════════════════════════════════════════════════════════════
def _is_kept_line(ln: dict) -> bool:
    return bool(ln.get("is_cut_panel")) or (ln.get("material_type") or "").lower() == "fabric"


def _sig(lines: list[dict]) -> tuple:
    return tuple((ln.get("code"), round(float(ln.get("qty") or 0), 6), bom_uom.norm_unit(ln.get("unit"))) for ln in lines)


async def apply_bom_groups(db, groups: list[dict], user: dict | None) -> dict:
    from routes.rahaza_bom import resolve_bom_materials
    from core.master_fill import bom_copy_to_missing
    by_model: dict = {}
    for g in groups:
        by_model.setdefault(g["model_id"], []).append(g)
    touched, created, uoms_added, problems, conflicts = set(), 0, 0, [], []
    n_added = n_removed = n_unchanged = 0
    for model_id, gs in by_model.items():
        for ln in (ln for g in gs for ln in g["lines"] if ln.get("add_pcs_uom")):
            mat = await db.rahaza_materials.find_one({"id": ln["material_id"]}, {"_id": 0})
            row = pcs_uom_row(mat) if mat else None
            if row:
                from core.uom import resolve_uoms
                await db.rahaza_materials.update_one({"id": mat["id"]}, {"$set": {"uoms": resolve_uoms(mat) + [row], "updated_at": _now()}})
                uoms_added += 1
        variants = (await load_model_variants(db, [model_id])).get(model_id) or []
        # baris aksesoris baru per varian tujuan (kelompok belakangan menimpa kode yang sama)
        per_variant: dict[str, dict] = {}
        for g in gs:
            resolved, prob = await resolve_bom_materials(db, [{"material_id": ln["material_id"], "code": ln["code"], "name": ln["name"], "qty": ln["qty"],
                                                              "unit": ln["unit"], "material_type": ln["material_type"], "notes": ""} for ln in g["lines"]],
                                                         strict_accessory=False)
            problems += [f"{g['model_code']}: {p.get('code')} — {p.get('reason')}" for p in prob]
            for v in target_variants(g, variants):
                slot = per_variant.setdefault(v["sku"], {"variant": v, "lines": {}})
                for r in resolved:
                    if r["code"] in slot["lines"] and abs(float(slot["lines"][r["code"]]["qty"]) - float(r["qty"])) > 1e-9:
                        conflicts.append(f"{g['model_code']} {v['sku']}: {r['code']} qty {slot['lines'][r['code']]['qty']} → {r['qty']} (kelompok baris {g['row']} menimpa)")
                    slot["lines"][r["code"]] = dict(r)
        boms = await db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}, "is_active": True}, {"_id": 0}).to_list(2000)
        keys = {(b.get("size_id"), (b.get("color_code") or "").upper()) for b in boms}
        missing = [s["variant"] for s in per_variant.values() if (s["variant"].get("size_id"), (s["variant"].get("color_code") or "").upper()) not in keys]
        if missing and boms:
            await bom_copy_to_missing(db, user, model_id)
        elif missing:
            for v in missing:
                await db.rahaza_boms.insert_one({"id": str(uuid.uuid4()), "model_id": model_id, "size_id": v.get("size_id"), "color": v.get("color_name"),
                                                 "color_code": (v.get("color_code") or "").upper() or None, "version": 1, "is_active": True, "active": True,
                                                 "materials": [], "notes": "BOM dasar dari sheet BOM_AKSESORIS (kain/potongan belum ada — lengkapi di RnD)",
                                                 "created_by": (user or {}).get("id", "system"), "created_at": _now(), "updated_at": _now()})
                created += 1
        boms = await db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}, "is_active": True}, {"_id": 0}).to_list(2000)
        bom_by_key = {(b.get("size_id"), (b.get("color_code") or "").upper()): b for b in boms}
        for slot in per_variant.values():
            v = slot["variant"]
            b = bom_by_key.get((v.get("size_id"), (v.get("color_code") or "").upper()))
            if not b:
                continue
            old = list(b.get("materials") or [])
            keep = [ln for ln in old if _is_kept_line(ln)]
            old_acc = [ln for ln in old if not _is_kept_line(ln)]
            new_acc = [dict(x) for x in slot["lines"].values()]
            if _sig(old_acc) == _sig(new_acc):
                n_unchanged += 1
                continue
            await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": keep + new_acc, "updated_at": _now(), "accessories_source": "BOM_AKSESORIS"},
                                                              "$push": {"change_log": {"at": _now(), "by": (user or {}).get("name", "system"),
                                                                                       "note": f"BOM_AKSESORIS ganti utuh: {len(old_acc)} baris aksesoris → {len(new_acc)}"}}})
            touched.add(b["id"])
            n_added += len(new_acc)
            n_removed += len(old_acc)
    return {"bom_models": len(by_model), "bom_groups": len(groups), "bom_base_created": created, "boms_touched": len(touched), "boms_unchanged": n_unchanged,
            "bom_lines_appended": n_added, "bom_lines_replaced": n_removed, "bom_lines_updated": 0, "bom_pcs_uoms_added": uoms_added,
            "bom_problems": problems[:20], "bom_conflicts": conflicts[:20]}


# ═══════════════════════════════════════════════════════════════════════════
# HPP — tanda "belum tervalidasi"
# ═══════════════════════════════════════════════════════════════════════════
async def flag_hpp_validation(db) -> dict:
    """Model yang BOM-nya memakai material berharga 0 atau kemasan tanpa isi (harga per kemasan tak jelas) → hpp_validation.status = belum_tervalidasi."""
    mats = {m["id"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}}, {"_id": 0, "id": 1, "code": 1, "unit": 1, "base_uom": 1, "pack_size": 1, "unit_cost": 1}).to_list(30000)}
    reasons_by_model: dict[str, dict] = {}
    async for b in db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True}, {"_id": 0, "model_id": 1, "materials": 1}):
        r = reasons_by_model.setdefault(b["model_id"], {"harga_0": set(), "kemasan": set(), "has_bom": True})
        for ln in b.get("materials") or []:
            if ln.get("is_cut_panel"):
                continue
            m = mats.get(ln.get("material_id"))
            if not m:
                continue
            if float(m.get("unit_cost") or 0) <= 0:
                r["harga_0"].add(m["code"])
            if bom_uom.norm_unit(m.get("base_uom") or m.get("unit")) in bom_uom.PACKAGING_UNITS and float(m.get("pack_size") or 0) <= 1:
                r["kemasan"].add(m["code"])
    now, n_un, n_ok = _now(), 0, 0
    stopped = {d["_id"] for d in await db.rahaza_model_variants.aggregate([
        {"$group": {"_id": "$model_id", "aktif": {"$sum": {"$cond": [{"$ne": ["$active", False]}, 1, 0]}}}}, {"$match": {"aktif": 0}}]).to_list(5000)}
    async for m in db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1}):
        if m["id"] in stopped:
            await db.rahaza_models.update_one({"id": m["id"]}, {"$set": {"hpp_validation": {"status": "dihentikan", "reasons": ["semua SKU model ini dinonaktifkan (sudah tidak dijual)"], "at": now}}})
            continue
        r = reasons_by_model.get(m["id"])
        reasons = []
        if not r:
            reasons.append("BOM belum ada")
        else:
            if r["harga_0"]:
                reasons.append(f"{len(r['harga_0'])} material harga 0: {', '.join(sorted(r['harga_0'])[:8])}")
            if r["kemasan"]:
                reasons.append(f"{len(r['kemasan'])} material satuan roll/pack tanpa isi kemasan: {', '.join(sorted(r['kemasan'])[:8])}")
        status = "belum_tervalidasi" if reasons else "tervalidasi"
        n_un += status == "belum_tervalidasi"
        n_ok += status == "tervalidasi"
        await db.rahaza_models.update_one({"id": m["id"]}, {"$set": {"hpp_validation": {"status": status, "reasons": reasons, "at": now}}})
    return {"hpp_unvalidated": n_un, "hpp_validated": n_ok}
