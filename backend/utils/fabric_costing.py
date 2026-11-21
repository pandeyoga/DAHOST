"""
Fabric costing from Tech Pack `fabric_consumption` (+ `fabrics`) and material prices.

Shared by:
  - RnD HPP Calculator (#1)  → auto fabric cost per pcs (per size)
  - RnD Pola & Marking (#3a) → auto fabric usage & fabric HPP per pcs

meters_per_pcs = (length_cm / 100) / yield_pcs   (length is fabric length that yields
`yield_pcs` pieces at the given width). Fallback to length/100 if yield missing.

Price resolution order per fabric name (2026-08-02: SADAR SATUAN):
  1. dewi_rnd_materials.material_name (case-insensitive) → price_per_unit/price_per_meter
  2. dewi_rnd_materials.material_code (== name upper)     → idem
  3. rahaza_materials.name (case-insensitive)             → unit_cost (per SATUAN DASAR)
Unresolved → price 0 + source 'unresolved' (UI prompts to set price in Riset Material).

CATATAN PENTING: konsumsi kain dihitung dalam METER, sedangkan `rahaza_materials.unit_cost`
adalah harga per satuan dasar material — untuk kain rajut satuan dasarnya biasanya **kg**.
Dulu harga per kg dipakai langsung sebagai harga per meter (biaya kain salah besar).
Sekarang harga per kg dikonversi ke harga per meter memakai gramasi (gsm) & lebar (cm)
material, atau kemasan/uoms yang terdaftar; bila datanya belum ada, harga TIDAK dipakai
dan sumbernya dilaporkan `needs_gsm_width` supaya RnD melengkapi datanya.
"""
import re

from core import bom_uom


def _num(v, d=0.0):
    try:
        if v is None or v == "":
            return float(d)
        return float(v)
    except (TypeError, ValueError):
        return float(d)


def _price_per_meter_from_base(material: dict, price_base: float):
    """Ubah harga per satuan dasar material → harga per METER.

    Return (price_per_meter, note). price_per_meter None bila tak bisa dikonversi.
    """
    base = bom_uom.norm_unit(material.get("base_uom") or material.get("unit") or "")
    if not base or price_base <= 0:
        return None, "no_price"
    if base in ("m", "meter", "mtr"):
        return price_base, ""
    # 1 meter = `factor` satuan dasar → harga/meter = factor × harga/satuan dasar
    factor, _base, status, _note = bom_uom.line_factor(material, "m")
    if status in ("uom", "global", "fabric") and factor:
        return price_base * factor, status
    return None, "needs_gsm_width"


async def resolve_fabric_price(db, name: str):
    name = (name or "").strip()
    if not name:
        return 0.0, "empty"
    rx = {"$regex": f"^{re.escape(name)}$", "$options": "i"}
    for query, src in ((({"material_name": rx}), "rnd_material"),
                       (({"material_code": name.upper()}), "rnd_material_code")):
        m = await db.dewi_rnd_materials.find_one(query, {"_id": 0})
        if not m:
            continue
        price = _num(m.get("price_per_unit") or m.get("price_per_meter"))
        unit = bom_uom.norm_unit(m.get("price_unit") or m.get("unit") or "m")
        if price <= 0:
            continue
        if unit in ("m", "meter", "mtr"):
            return price, src
        # Harga RnD dinyatakan dalam satuan lain (mis. per kg) → coba konversi ke meter
        mat = await db.rahaza_materials.find_one({"name": rx, "type": {"$ne": "fg"}}, {"_id": 0}) or {}
        gf = bom_uom.global_factor("m", unit)
        if gf:
            return price * gf, f"{src}_converted"
        conv, _n = _price_per_meter_from_base({**mat, "base_uom": unit}, price)
        if conv:
            return conv, f"{src}_converted"
        return 0.0, f"{src}_needs_conversion"

    r = await db.rahaza_materials.find_one({"name": rx, "type": {"$ne": "fg"}}, {"_id": 0})
    if r and _num(r.get("unit_cost")) > 0:
        conv, note = _price_per_meter_from_base(r, _num(r.get("unit_cost")))
        if conv:
            base = bom_uom.norm_unit(r.get("base_uom") or r.get("unit") or "")
            return conv, "rahaza_material" if base in ("m", "meter") else "rahaza_material_converted"
        # Harga per kg tanpa gramasi/lebar → JANGAN dipakai sebagai harga per meter.
        return 0.0, "rahaza_material_needs_gsm_width"
    return 0.0, "unresolved"


async def harga_kain(db, fb: dict, satuan: str):
    """(harga per `satuan` pakai ('m' atau 'kg'), sumber) — 21 Nov 2026 (owner): SATU aturan harga kain untuk semua
    layar R&D = master per warna (`master_code`) → master keluarga (`kode`) → Riset Material/nama (aturan lama).
    Harga master per satuan dasar dikonversi ke satuan pakai (yard → meter; kg ⇄ meter butuh gramasi & lebar)."""
    cands = []
    if fb.get("master_code"):
        m = await db.rahaza_materials.find_one({"code": str(fb["master_code"]).upper()}, {"_id": 0})
        if m:
            cands.append((m, "master_warna"))
    if fb.get("kode"):
        async for m in db.rahaza_materials.find(
                {"code": {"$regex": f"^{re.escape(str(fb['kode']).upper())}-"}, "type": "fabric",
                 "active": {"$ne": False}, "unit_cost": {"$gt": 0}}, {"_id": 0}).limit(1):
            cands.append((m, "master_keluarga"))
    for m, src in cands:
        base = bom_uom.norm_unit(m.get("base_uom") or m.get("unit") or "")
        price = _num(m.get("unit_cost"))
        if price <= 0:
            continue
        if satuan == "kg":
            gf = bom_uom.global_factor("kg", base)          # 1 kg = gf satuan dasar
            if gf:
                return price * gf, src
            kgm = bom_uom.fabric_kg_per_meter(m)
            if kgm and base in ("m", "meter", "yard", "cm"):
                per_m, _n = _price_per_meter_from_base(m, price)
                if per_m:
                    return per_m / kgm, f"{src}_dikonversi"
            continue
        per_m, _n = _price_per_meter_from_base(m, price)
        if per_m:
            return per_m, src
    if satuan == "kg":
        r = await db.dewi_rnd_materials.find_one(
            {"$or": [{"material_code": str(fb.get("kode") or "").upper() or "__"},
                     {"material_name": {"$regex": f"^{re.escape(str(fb.get('name') or '').strip())}$", "$options": "i"}}]},
            {"_id": 0})
        if r and bom_uom.norm_unit(r.get("price_unit") or r.get("unit") or "") == "kg" and _num(r.get("price_per_unit")) > 0:
            return _num(r.get("price_per_unit")), "rnd_material"
        return 0.0, "unresolved"
    return await resolve_fabric_price(db, fb.get("name"))


def _pakai_baris(e: dict) -> tuple:
    """(qty per pcs, satuan 'm'|'kg') dari satu baris pemakaian; kg = berat ÷ hasil, cm = panjang ÷ 100 ÷ hasil."""
    yld = _num(e.get("yield_pcs"))
    if (e.get("satuan") == "kg") or (e.get("weight_kg") not in (None, "") and not _num(e.get("length_cm"))):
        kg = _num(e.get("weight_kg"))
        return (kg / yld if yld > 0 else kg), "kg"
    length = _num(e.get("length_cm"))
    return ((length / 100.0) / yld if yld > 0 else (length / 100.0)), "m"


async def compute_fabric_cost(db, techpack: dict, size: str = None) -> dict:
    """Return per-size fabric cost breakdown derived from a tech pack.

    21 Nov 2026: baris pemakaian ber-satuan kg (kain knit: berat ÷ hasil) didukung; harga kain satu aturan
    (`harga_kain`). Per ukuran: `meters_per_pcs` (baris meter), `kg_per_pcs` (baris kg), `fabric_cost_per_pcs`,
    dan `pakai` {qty, satuan, harga} untuk mengisi kalkulator (satu satuan; campuran → 1 set × biaya)."""
    fabrics = techpack.get("fabrics") or []
    consumption = techpack.get("fabric_consumption") or []
    by_role = {}
    for fb in fabrics:
        by_role.setdefault(fb.get("role", "main"), fb)
    cache: dict = {}

    async def price_for(role, satuan):
        fb = by_role.get(role) or by_role.get("main") or {}
        key = (fb.get("master_code") or fb.get("kode") or fb.get("name"), satuan)
        if key not in cache:
            cache[key] = await harga_kain(db, fb, satuan) if fb else (0.0, "unresolved")
        return cache[key]

    priced = []
    for fb in fabrics:
        sat = "kg" if fb.get("satuan_pakai") == "kg" else "m"
        price, src = await price_for(fb.get("role", "main"), sat)
        priced.append({"name": fb.get("name"), "role": fb.get("role", "main"), "kode": fb.get("kode") or "",
                       "price_per_meter" if sat == "m" else "price_per_kg": price, "price_source": src})

    sizes = {}
    for e in consumption:
        sz = (e.get("size") or "ALLSIZE")
        role = e.get("fabric_role", "main")
        qty, sat = _pakai_baris(e)
        price, src = await price_for(role, sat)
        cost = qty * price
        fb = by_role.get(role) or by_role.get("main") or {}
        s = sizes.setdefault(sz, {"size": sz, "entries": [], "meters_per_pcs": 0.0, "kg_per_pcs": 0.0,
                                  "fabric_cost_per_pcs": 0.0, "_m_cost": 0.0})
        s["entries"].append({
            "fabric_role": role, "fabric_name": fb.get("name", ""), "kode": fb.get("kode") or "",
            "satuan": sat, "qty_per_pcs": round(qty, 4), "price_per_unit": price,
            "length_cm": _num(e.get("length_cm")), "weight_kg": _num(e.get("weight_kg")),
            "yield_pcs": _num(e.get("yield_pcs")),
            "meters_per_pcs": round(qty, 4) if sat == "m" else 0.0,
            "price_per_meter": price if sat == "m" else 0.0,
            "cost_per_pcs": round(cost, 2), "price_source": src,
        })
        if sat == "m":
            s["meters_per_pcs"] += qty
            s["_m_cost"] += cost
        else:
            s["kg_per_pcs"] += qty
        s["fabric_cost_per_pcs"] += cost

    size_list = []
    for s in sizes.values():
        wp = (s["_m_cost"] / s["meters_per_pcs"]) if s["meters_per_pcs"] > 0 else 0.0
        sats = {x["satuan"] for x in s["entries"]}
        if sats == {"kg"}:
            pakai = {"qty": round(s["kg_per_pcs"], 4), "satuan": "kg",
                     "harga": round(s["fabric_cost_per_pcs"] / s["kg_per_pcs"], 2) if s["kg_per_pcs"] else 0.0}
        elif sats == {"m"}:
            pakai = {"qty": round(s["meters_per_pcs"], 4), "satuan": "m", "harga": round(wp, 2)}
        else:
            pakai = {"qty": 1, "satuan": "set", "harga": round(s["fabric_cost_per_pcs"], 2)}
        size_list.append({
            "size": s["size"],
            "entries": s["entries"],
            "meters_per_pcs": round(s["meters_per_pcs"], 4),
            "kg_per_pcs": round(s["kg_per_pcs"], 4),
            "fabric_cost_per_pcs": round(s["fabric_cost_per_pcs"], 2),
            "weighted_price_per_meter": round(wp, 2),
            "pakai": pakai,
        })
    size_list.sort(key=lambda x: str(x["size"]))
    avg = round(sum(x["fabric_cost_per_pcs"] for x in size_list) / len(size_list), 2) if size_list else 0.0
    result = {
        "fabrics": priced,
        "sizes": size_list,
        "avg_fabric_cost_per_pcs": avg,
        "has_unresolved_price": any(p["price_source"] == "unresolved" for p in priced),
    }
    if size and size_list:
        sel = next((x for x in size_list if str(x["size"]).upper() == str(size).upper()), None)
        result["selected"] = sel or size_list[0]
    elif size_list:
        result["selected"] = size_list[0]
    else:
        result["selected"] = None
    return result
