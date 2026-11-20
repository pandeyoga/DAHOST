"""core/bom_techpack.py — BOM produksi dibuat dari BOM tech pack R&D (owner 20 Nov 2026, pertanyaan Ega R&D).

Dulu promosi style ke produksi hanya menyimpan BOM tech pack sebagai SALINAN REFERENSI (`rahaza_models.techpack`);
BOM produksi (`rahaza_boms`, satu per ukuran × warna) harus diketik ulang di Master Produk › BOM. Modul ini membuatnya
dari tech pack terbaru style asal model, untuk setiap varian aktif yang BELUM punya BOM (BOM yang ada tidak disentuh):

* baris POTONGAN '1 pcs' (master potongan `CUT-…`, `core.cut_panel_master`) dengan RESEP KAIN dari tab Bahan:
  kain dicocokkan ke master kain per warna (Riset Material `KN-RMT` + warna → `KN-RMT-<WARNA>`). Kain tanpa warna di
  tech pack memakai warna varian; kain berwarna dipilih yang warnanya = warna varian, dan pasangannya (mis. polos
  utama + motif kombinasi yang ditulis berurutan) ikut. Perkiraan per pcs = panjang ÷ isi (cm → satuan kain master);
  bila satuannya tidak bisa dikonversi, perkiraannya dikosongkan;
* baris AKSESORIS tech pack untuk warna/motif varian itu + baris tanpa warna (berlaku semua motif), qty & satuan
  apa adanya, dikonversi ke satuan dasar lewat `routes.rahaza_bom.resolve_bom_materials` (sama dengan editor BOM).

Yang tidak bisa dipastikan TIDAK ditebak: dilaporkan per varian di `catatan` (kain belum ada di master, aksesoris
belum terhubung master, warna tech pack yang tidak cocok varian mana pun, varian tanpa warna).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from core import bom_uom
from core.cut_panel_master import bom_line_for_panel, ensure_panel

PERAN = {"main": "Utama", "utama": "Utama", "combination": "Kombinasi", "kombinasi": "Kombinasi",
         "collar": "Kerah", "kerah": "Kerah", "sleeve": "Lengan", "lining": "Furing", "furing": "Furing",
         "interlining": "Kain keras"}


def _now():
    return datetime.now(timezone.utc)


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def techpack_model(db, model: dict) -> dict | None:
    """Tech pack terbaru style asal model; cadangan: salinan yang disimpan saat promosi (hanya BOM)."""
    sid = (model or {}).get("rnd_style_id")
    tp = None
    if sid:
        tp = (await db.dewi_rnd_tech_packs.find_one({"style_id": sid, "is_latest": True}, {"_id": 0})
              or await db.dewi_rnd_tech_packs.find_one({"style_id": sid}, {"_id": 0}, sort=[("created_at", -1)]))
    if not tp and (model or {}).get("techpack"):
        tp = dict(model["techpack"])
    return tp


# ── aksesoris per warna ───────────────────────────────────────────────────────
def _warna_item(b: dict) -> tuple:
    return (str(b.get("color_code") or "").strip().upper(), str(b.get("color_name") or "").strip())


def baris_untuk_warna(items: list, color_code: str, color_name: str) -> list:
    """Baris BOM tech pack untuk satu warna varian: baris tanpa warna + baris yang kode/nama warnanya sama."""
    cc, cn = (color_code or "").upper(), _norm(color_name)
    out = []
    for b in items or []:
        kode, nama = _warna_item(b)
        if not kode and not nama:
            out.append(b)
        elif (kode and kode == cc) or (nama and cn and _norm(nama) == cn):
            out.append(b)
    return out


def warna_tak_terpakai(items: list, variants: list) -> list:
    """Warna/motif di BOM tech pack yang tidak cocok dengan varian mana pun (aksesorisnya tidak masuk BOM)."""
    kode = {(v.get("color_code") or "").upper() for v in variants} - {""}
    nama = {_norm(v.get("color_name")) for v in variants} - {""}
    out = []
    for b in items or []:
        k, n = _warna_item(b)
        cocok = (k and k in kode) or (n and _norm(n) in nama)
        if (k or n) and not cocok:
            label = n or k
            if label not in out:
                out.append(label)
    return out


# ── kain per warna ────────────────────────────────────────────────────────────
def _berpasangan(fabrics: list) -> bool:
    """Kain ditulis berpasangan (peran A, peran B, peran A, peran B, …), mis. polos utama + motif kombinasi."""
    if len(fabrics) < 2 or len(fabrics) % 2:
        return False
    a, b = fabrics[0].get("role"), fabrics[1].get("role")
    return a != b and all(f.get("role") == (a if i % 2 == 0 else b) for i, f in enumerate(fabrics))


def kain_untuk_warna(fabrics: list, color_code: str) -> list:
    """[(entri kain tech pack, kode warna kain)] untuk satu varian."""
    fabrics = [f for f in (fabrics or []) if str(f.get("name") or "").strip()]
    cc = (color_code or "").upper()
    if not any(f.get("color_code") for f in fabrics):
        return [(f, cc) for f in fabrics]
    idx = next((i for i, f in enumerate(fabrics) if str(f.get("color_code") or "").upper() == cc), None)
    out, peran = [], set()
    if idx is not None:
        out.append((fabrics[idx], cc))
        peran.add(fabrics[idx].get("role"))
        if _berpasangan(fabrics):
            p = fabrics[idx ^ 1]
            out.append((p, str(p.get("color_code") or cc).upper()))
            peran.add(p.get("role"))
    for f in fabrics:   # kain tanpa warna di tech pack yang campur → ikut warna varian
        if not f.get("color_code") and f.get("role") not in peran:
            out.append((f, cc))
            peran.add(f.get("role"))
    return out


async def master_kain(db, nama: str, warna: str) -> dict | None:
    """Kain roll master untuk nama kain tech pack + warna: kode Riset Material + '-' + warna, atau nama sama."""
    nama = (nama or "").strip()
    if not nama or not warna:
        return None
    rx = {"$regex": f"^{re.escape(nama)}$", "$options": "i"}
    riset = await db.dewi_rnd_materials.find_one({"material_name": rx}, {"_id": 0, "material_code": 1})
    if riset and riset.get("material_code"):
        m = await db.rahaza_materials.find_one(
            {"code": f"{riset['material_code']}-{warna}".upper(), "type": "fabric", "active": {"$ne": False}},
            {"_id": 0})
        if m:
            return m
    return await db.rahaza_materials.find_one(
        {"name": rx, "type": "fabric", "active": {"$ne": False}, "is_cut_panel": {"$ne": True},
         "code": {"$regex": f"-{re.escape(warna)}$", "$options": "i"}}, {"_id": 0})


def meter_per_pcs(consumption: list, role: str, size_code: str) -> tuple:
    """(meter per pcs, catatan) dari tab Bahan: ukuran sama → ALLSIZE/kosong → satu-satunya ukuran yang ada."""
    rows = [c for c in consumption or [] if (c.get("fabric_role") or "main") == (role or "main")]
    if not rows:
        return None, ""
    sz = _norm(size_code)
    pick = [c for c in rows if _norm(c.get("size")) == sz]
    note = ""
    if not pick:
        pick = [c for c in rows if _norm(c.get("size")) in ("", "allsize")]
    if not pick and len({_norm(c.get("size")) for c in rows}) == 1:
        pick = rows
        note = f"perkiraan kain memakai ukuran {rows[0].get('size')}"
    if not pick:
        return None, ""
    c = pick[0]
    length, yld = _num(c.get("length_cm")), _num(c.get("yield_pcs"))
    if length <= 0:
        return None, note
    return (length / 100.0) / (yld if yld > 0 else 1.0), note


def qty_satuan_kain(meters: float | None, master: dict) -> float | None:
    if not meters:
        return None
    unit = master.get("base_uom") or master.get("unit") or ""
    gf = bom_uom.global_factor("m", unit)
    if gf:
        return round(meters * gf, 4)
    kgm = bom_uom.fabric_kg_per_meter(master) if bom_uom.norm_unit(unit) == "kg" else None
    return round(meters * kgm, 4) if kgm else None


# ── rencana + terapkan ────────────────────────────────────────────────────────
async def buat_dari_techpack(db, model_id: str, user: dict | None = None, *, terapkan: bool = True) -> dict:
    """Buat BOM produksi dari tech pack untuk setiap varian aktif model yang belum punya BOM.

    `terapkan=False` = pratinjau (tidak menulis apa pun). Hasil: {model, tech_pack, created/akan_dibuat, skipped,
    detail[{sku, baris, kain, catatan}], warna_tak_terpakai}."""
    from routes.rahaza_bom import resolve_bom_materials
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0, "sop_steps": 0})
    if not model:
        return {"ok": False, "message": "Model tidak ditemukan."}
    tp = await techpack_model(db, model)
    items = list((tp or {}).get("bom_items") or [])
    fabrics = list((tp or {}).get("fabrics") or [])
    consumption = list((tp or {}).get("fabric_consumption") or [])
    label = f"{model.get('code')} · {model.get('name')}"
    if not tp or not (items or fabrics):
        return {"ok": False, "model": label, "created": 0, "skipped": [], "detail": [],
                "message": f"{label} belum punya tech pack berisi BOM/bahan — isi BOM manual atau lengkapi tech pack R&D."}
    variants = await db.rahaza_model_variants.find(
        {"model_id": model_id, "active": {"$ne": False}}, {"_id": 0}).to_list(2000)
    sudah = {(b.get("size_id"), (b.get("color_code") or "").upper())
             async for b in db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}},
                                                {"_id": 0, "size_id": 1, "color_code": 1})}
    created, skipped, detail = 0, [], []
    for v in sorted(variants, key=lambda x: (x.get("color_code") or "", x.get("size_code") or "")):
        cc = (v.get("color_code") or "").upper()
        if not cc:
            skipped.append({"sku": v.get("sku"), "alasan": "varian tanpa warna — lengkapi warnanya di Varian / SKU"})
            continue
        if (v.get("size_id"), cc) in sudah:
            skipped.append({"sku": v.get("sku"), "alasan": "sudah punya BOM"})
            continue
        catatan, kain_label = [], []
        # potongan + resep kain
        resep, kain_asal, kain_doc = [], None, {}
        for f, warna in kain_untuk_warna(fabrics, cc):
            m = await master_kain(db, f.get("name"), warna)
            if not m:
                catatan.append(f"kain {str(f.get('name')).strip()} warna {warna} belum ada di master bahan")
                continue
            meters, note = meter_per_pcs(consumption, f.get("role"), v.get("size_code"))
            if note:
                catatan.append(note)
            qty = qty_satuan_kain(meters, m)
            if meters and qty is None:
                catatan.append(f"perkiraan {m.get('code')} kosong (satuan {m.get('unit')} belum bisa dihitung dari meter)")
            peran = PERAN.get(str(f.get("role") or "main").lower(), str(f.get("role") or "Utama").title())
            resep.append({"material_id": m["id"], "code": m["code"], "name": m.get("name") or "", "role": peran,
                          "qty_per_pcs": qty, "unit": m.get("unit") or ""})
            kain_label.append(f"{m['code']} ({peran})")
            kain_doc[m["code"]] = m
        utama = [r for r in resep if r["role"] == "Utama"] or resep
        if utama:
            kain_asal = kain_doc.get(utama[0]["code"])
        panel, _baru = await ensure_panel(
            db, model=model, color_code=cc, color_name=v.get("color_name") or cc, size_code=v.get("size_code") or "",
            size_id=v.get("size_id"), source_fabric=kain_asal, created_from="bom_techpack", apply=terapkan)
        baris = [bom_line_for_panel(panel)]
        if resep:
            baris[0]["fabric_recipe"] = resep
            try:   # validasi & penyelarasan resep yang sama dengan editor BOM (kain roll aktif, kode/satuan master)
                from core import resep_kain
                await resep_kain.lengkapi(db, baris)
            except Exception as e:  # noqa: BLE001 — resep tidak sah: potongan tetap dibuat tanpa resep
                baris[0].pop("fabric_recipe", None)
                catatan.append(f"resep kain tidak dipasang: {getattr(e, 'detail', e)}")
        # aksesoris warna ini + tanpa warna
        acc = [{"material_id": b.get("material_id") or None, "code": (b.get("material_code") or "").upper(),
                "name": b.get("master_name") or b.get("material") or "", "material_type": "accessory",
                "qty": _num(b.get("qty")) or 1.0, "unit": b.get("unit") or "pcs",
                "notes": str(b.get("spec") or "").strip()}
               for b in baris_untuk_warna(items, cc, v.get("color_name") or "")]
        resolved, problems = await resolve_bom_materials(db, acc, strict_accessory=False)
        buang = {p["index"] for p in problems if p.get("kind") != "uom"}
        for p in problems:
            catatan.append(f"aksesoris {p.get('name') or p.get('code')}: {p.get('reason')}"
                           + ("" if p.get("kind") == "uom" else " — tidak dimasukkan, tambahkan manual"))
        baris += [ln for i, ln in enumerate(resolved) if i not in buang]
        detail.append({"sku": v.get("sku"), "warna": v.get("color_name") or cc, "ukuran": v.get("size_code"),
                       "baris": len(baris), "aksesoris": len(baris) - 1, "kain": kain_label, "catatan": catatan})
        if terapkan:
            await db.rahaza_boms.insert_one({
                "id": str(uuid.uuid4()), "model_id": model_id, "size_id": v.get("size_id"),
                "color": v.get("color_name") or cc, "color_code": cc, "version": 1, "is_active": True, "active": True,
                "materials": baris, "source": "techpack", "techpack_id": tp.get("id") or tp.get("tech_pack_id"),
                "techpack_version": tp.get("version"),
                "notes": f"Dibuat dari BOM tech pack {tp.get('version') or ''}".strip()
                         + (" · " + "; ".join(catatan) if catatan else ""),
                "created_by": (user or {}).get("id", "system"), "created_at": _now(), "updated_at": _now()})
            sudah.add((v.get("size_id"), cc))
        created += 1
    return {"ok": True, "model": label, "tech_pack": tp.get("version"), "pratinjau": not terapkan,
            "created": created, "skipped": skipped, "detail": detail,
            "warna_tak_terpakai": warna_tak_terpakai(items, variants),
            "message": (f"{created} BOM {'akan dibuat' if not terapkan else 'dibuat'} dari tech pack {tp.get('version') or ''}"
                        f" untuk {label}" + (f" · {len(skipped)} varian dilewati" if skipped else ""))}
