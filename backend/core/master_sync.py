"""core.master_sync — SATU mesin sinkron master produk lintas portal (idempoten, aman diulang).

Keputusan owner 2026-09-12 ("data jangan setengah-setengah"):
A. Varian SSOT `rahaza_model_variants` = gabungan BOM ∪ FG. Kombinasi BOM tanpa FG → varian + FG (stok 0, SKU kanonik);
   FG tanpa varian → varian dibuat & ditautkan (`variant_id`). FG tanpa BOM hanya DILAPORKAN (BOM diisi RnD).
B. Tiap model → 1 Style RnD (kode = kode model) + Varian RnD per warna (daftar ukuran & SKU). Status `promoted` bila
   semua varian punya BOM, selain itu `approved_for_launch` (terlihat "belum lengkap"). Tech pack TIDAK dikarang.
   13 Nov 2026: style dicari lewat TAUTAN (`rnd_style_id`/`promoted_to_model_id`) dulu, baru kode — ganti kode di
   R&D/Master Produk tidak lagi membuat style kembar (`_cocokkan_style`, `core.ganti_kode_produk`).
C. Karyawan ↔ user: tautan balik `rahaza_employees.user_id`/`user_email` dari `users.employee_id`.
D. Material ↔ Kategori Material master (`category`/`category_id`; teks bebas lama disimpan di `sub_category`);
   satuan yang dipakai material (pack, roll) ada di master satuan gudang.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from core import ganti_kode_produk as gkp
from utils.variant_ssot import build_variant_sku, ensure_fg_material


def _now():
    return datetime.now(timezone.utc)


def _uid():
    return str(uuid.uuid4())


async def _load(db):
    models = {m["id"]: m for m in await db.rahaza_models.find({}, {"_id": 0, "sop_steps": 0}).to_list(5000)}
    sizes = {s["id"]: s for s in await db.rahaza_sizes.find({}, {"_id": 0}).to_list(500)}
    colors_by_code = {(c.get("code") or "").upper(): c for c in await db.rahaza_colors.find({}, {"_id": 0}).to_list(2000)}
    return models, sizes, colors_by_code


async def _sync_variants(db, report: dict, user):
    models, sizes, colors = await _load(db)
    variants = await db.rahaza_model_variants.find({"active": True}, {"_id": 0}).to_list(20000)
    by_key = {(v["model_id"], v.get("size_id"), (v.get("color_code") or "").upper()): v for v in variants}
    created_from_fg, created_from_bom, fg_created, linked = 0, 0, 0, 0

    async def _make_variant(model_id, size_id, color_code, color_doc, fg=None):
        model, size = models.get(model_id), sizes.get(size_id)
        if not model or not size:
            return None
        cdoc = color_doc or colors.get(color_code) or {}
        sku = (fg or {}).get("code") or build_variant_sku(model["code"], color_code, size["code"])
        doc = {"id": _uid(), "model_id": model_id, "model_code": model["code"], "model_name": model["name"],
               "size_id": size_id, "size_code": size["code"], "color_id": (fg or {}).get("color_id") or cdoc.get("id"),
               "color_code": color_code, "color_name": (fg or {}).get("color_name") or cdoc.get("name") or color_code,
               "color_hex": (fg or {}).get("color_hex") or cdoc.get("hex"), "sku": sku.upper(), "barcode": "", "notes": "",
               "active": True, "created_at": _now(), "updated_at": _now(), "created_from": "master_sync"}
        await db.rahaza_model_variants.insert_one(doc)
        by_key[(model_id, size_id, color_code)] = doc
        return doc

    # A1: FG → varian
    async for fg in db.rahaza_materials.find({"type": "fg", "active": {"$ne": False}}, {"_id": 0}):
        key = (fg.get("model_id"), fg.get("size_id"), (fg.get("color_code") or "").upper())
        v = by_key.get(key)
        if not v:
            v = await _make_variant(*key, None, fg=fg)
            if not v:
                report.setdefault("fg_unresolvable", []).append(fg["code"])
                continue
            created_from_fg += 1
        if fg.get("variant_id") != v["id"]:
            await db.rahaza_materials.update_one({"id": fg["id"]}, {"$set": {"variant_id": v["id"], "updated_at": _now()}})
            linked += 1
        if not fg.get("category_id") or not fg.get("model_name"):
            await ensure_fg_material(db, v, user=user)  # backfill kategori/berat/HPP FG dari model (SSOT)
    # A2: BOM → varian + FG
    bom_keys = set()
    async for b in db.rahaza_boms.find({"active": {"$ne": False}}, {"_id": 0, "model_id": 1, "size_id": 1, "color_code": 1, "color": 1}):
        key = (b["model_id"], b.get("size_id"), (b.get("color_code") or "").upper())
        bom_keys.add(key)
        if key in by_key:
            continue
        cdoc = colors.get(key[2]) or {"code": key[2], "name": b.get("color") or key[2]}
        v = await _make_variant(*key, cdoc)
        if not v:
            report.setdefault("bom_unresolvable", []).append(f"{key}")
            continue
        created_from_bom += 1
        fg = await ensure_fg_material(db, v, user=user)
        if fg and not fg.get("variant_id"):
            await db.rahaza_materials.update_one({"id": fg["id"]}, {"$set": {"variant_id": v["id"]}})
        fg_created += 1
    report["variants"] = {"total": len(by_key), "created_from_fg": created_from_fg, "created_from_bom": created_from_bom,
                          "fg_created": fg_created, "fg_linked": linked,
                          "variants_without_bom": len([k for k in by_key if k not in bom_keys])}
    return by_key, bom_keys


def _cocokkan_style(models: dict, styles: list) -> tuple[dict, list]:
    """{model_id: style} untuk model aktif + daftar konflik (fungsi murni).

    13 Nov 2026 (laporan R&D "ganti nama tidak berubah, ganti kode jadi dobel", owner: dibenarkan): dulu style dicari
    HANYA lewat kode (`styles.get(model["code"])`). Kode yang diubah di R&D, di Master Produk, atau saat promosi
    (`model_code` ≠ kode style) membuat pencarian meleset → style KEDUA dibuat untuk produk yang sama. Sekarang:
      1. tautan dulu — `model.rnd_style_id` / `style.promoted_to_model_id` (`core.ganti_kode_produk.pilih_style_utama`);
      2. baru kode — hanya style yang belum tertaut model hidup lain;
      3. style baru hanya dibuat bila model belum punya style DAN kodenya belum dipakai style lain (selain itu konflik
         dilaporkan, tidak dibuat kembaran)."""
    hidup = {mid: m for mid, m in models.items() if m.get("active") is not False}
    per_model: dict = {}
    for s in styles:
        if s.get("promoted_to_model_id"):
            per_model.setdefault(s["promoted_to_model_id"], []).append(s)
    by_id = {s["id"]: s for s in styles}
    pasangan, dipakai, konflik = {}, set(), []
    for mid, m in hidup.items():   # 1 · tautan
        kandidat = list(per_model.get(mid, []))
        if m.get("rnd_style_id") in by_id and by_id[m["rnd_style_id"]] not in kandidat:
            kandidat.append(by_id[m["rnd_style_id"]])
        st = gkp.pilih_style_utama(m, [s for s in kandidat if s["id"] not in dipakai])
        if st:
            pasangan[mid] = st
            dipakai.add(st["id"])
    by_code: dict = {}
    for s in styles:
        by_code.setdefault((s.get("style_code") or "").upper(), []).append(s)
    for mid, m in hidup.items():   # 2 · kode (style belum tertaut model hidup lain)
        if mid in pasangan:
            continue
        for s in by_code.get((m.get("code") or "").upper(), []):
            pemilik = s.get("promoted_to_model_id")
            bebas = not pemilik or pemilik == mid or pemilik not in hidup
            if s["id"] not in dipakai and bebas and not s.get("merged_into_style_id"):
                pasangan[mid] = s
                dipakai.add(s["id"])
                break
        else:
            if by_code.get((m.get("code") or "").upper()):
                konflik.append(f"{m.get('code')}: kode sudah dipakai style R&D lain — style tidak dibuat (rapikan manual)")
    return pasangan, konflik


async def _sync_rnd_styles(db, report: dict, by_key: dict, bom_keys: set, user):
    models, sizes, _ = await _load(db)
    styles = await db.dewi_rnd_styles.find({}, {"_id": 0, "id": 1, "style_code": 1, "style_name": 1, "promoted_to_model_id": 1,
                                                "status": 1, "master_sync": 1, "merged_into_style_id": 1,
                                                "created_at": 1}).to_list(5000)
    pasangan, konflik = _cocokkan_style(models, styles)
    pemegang = {(s.get("style_code") or "").upper(): s["id"] for s in styles}   # kode style unik (index)
    # Kode style tertaut mengikuti kode master (SSOT). Dipindah bertahap: kode tujuan harus bebas dulu (index unik
    # `style_code`), jadi style yang kodenya baru dilepas style lain menyusul di putaran berikutnya.
    pindah = {mid: st for mid, st in pasangan.items()
              if (models[mid].get("code") or "").upper() and (st.get("style_code") or "").upper() != (models[mid].get("code") or "").upper()}
    code_fixed = 0
    while pindah:
        maju = False
        for mid in list(pindah):
            st, kode = pindah[mid], (models[mid].get("code") or "").upper()
            if pemegang.get(kode) not in (None, st["id"]):
                continue
            try:
                await db.dewi_rnd_styles.update_one({"id": st["id"]}, {"$set": {"style_code": models[mid]["code"], "updated_at": _now()}})
            except DuplicateKeyError:      # kode beda huruf besar/kecil di DB — jangan gagalkan start backend
                pemegang[kode] = "?"
                continue
            pemegang.pop((st.get("style_code") or "").upper(), None)
            pemegang[kode] = st["id"]
            pasangan[mid] = {**st, "style_code": models[mid]["code"]}
            del pindah[mid]
            code_fixed += 1
            maju = True
        if not maju:
            break
    for mid, st in pindah.items():
        konflik.append(f"{models[mid].get('code')}: style tertaut masih berkode {st.get('style_code')} — kode master dipegang "
                       "style lain (rapikan dengan skrip 2026_11_13_rapikan_style_rnd_dobel)")
    created, updated, rnd_variants = 0, 0, 0
    per_model: dict = {}
    for (mid, sid_, ccode), v in by_key.items():
        per_model.setdefault(mid, []).append((sid_, ccode, v))
    for mid, model in models.items():
        if model.get("active") is False:
            continue
        vs = per_model.get(mid, [])
        complete = bool(vs) and all((mid, s, c) in bom_keys for s, c, _ in vs)
        status = "promoted" if complete else "approved_for_launch"
        size_docs = {s: sizes[s] for s, _, _ in vs if s in sizes}
        size_list = [d["code"] for d in sorted(size_docs.values(), key=lambda d: (d.get("order_seq", 50), d["code"]))]
        st = pasangan.get(mid)
        kode = (model.get("code") or "").upper()
        base = {**gkp.field_style_dari_model(model),
                "promoted_to_model_id": mid, "size_list": size_list, "rnd_type": "internal_product", "updated_at": _now(),
                "sync_note": "Lengkap: semua varian punya BOM" if complete else ("Belum lengkap: ada varian tanpa BOM" if vs else "Belum lengkap: belum ada varian/BOM"),
                "master_sync": True}
        if not st:
            if kode in pemegang:      # konflik sudah dicatat `_cocokkan_style` — jangan buat kembaran
                continue
            doc = {"id": _uid(), "style_code": model["code"], **base, "buyer": "", "season": "", "status": status,
                   "client_id": None, "client_name": "", "techpack_url": None, "techpack_name": None, "design_images": list(model.get("image_paths") or []),
                   "variants": [], "size_map": [], "created_by": (user or {}).get("id", "system"), "created_by_name": (user or {}).get("name", "master_sync"),
                   "created_at": _now(), "promoted_at": model.get("created_at")}
            try:
                await db.dewi_rnd_styles.insert_one(doc)
            except DuplicateKeyError:
                konflik.append(f"{model.get('code')}: kode sudah dipakai style R&D lain — style tidak dibuat (rapikan manual)")
                continue
            pemegang[kode] = doc["id"]
            st = doc
            created += 1
        else:
            patch = dict(base)
            if st.get("master_sync") or st.get("status") in ("promoted", "approved_for_launch"):
                patch["status"] = status
            await db.dewi_rnd_styles.update_one({"id": st["id"]}, {"$set": patch})
            updated += 1
            await db.dewi_rnd_variants.update_many(
                {"style_id": st["id"], "$or": [{"style_code": {"$ne": st["style_code"]}}, {"style_name": {"$ne": model["name"]}}]},
                {"$set": {"style_code": st["style_code"], "style_name": model["name"]}})
        if model.get("rnd_style_id") != st["id"] or model.get("rnd_style_code") != st["style_code"]:
            await db.rahaza_models.update_one({"id": mid}, {"$set": {"rnd_style_id": st["id"], "rnd_style_code": st["style_code"]}})
        # Varian RnD per warna
        by_color: dict = {}
        for s, c, v in vs:
            by_color.setdefault(c, []).append(v)
        existing = {(x.get("color_code") or "").upper(): x for x in await db.dewi_rnd_variants.find({"style_id": st["id"]}, {"_id": 0}).to_list(500)}
        for c, vlist in by_color.items():
            rows = sorted(({"size": x["size_code"], "sku": x["sku"], "qty_plan": 0.0, "variant_id": x["id"]} for x in vlist), key=lambda r: r["size"])
            ex = existing.get(c)
            if ex:
                have = {r["sku"] for r in (ex.get("sizes") or [])}
                if {r["sku"] for r in rows} - have:
                    await db.dewi_rnd_variants.update_one({"id": ex["id"]}, {"$set": {"sizes": rows, "updated_at": _now()}})
                continue
            v0 = vlist[0]
            await db.dewi_rnd_variants.insert_one({"id": _uid(), "style_id": st["id"], "style_code": st["style_code"], "style_name": model["name"],
                                                   "color_id": v0.get("color_id"), "color": v0.get("color_name") or c, "color_code": c,
                                                   "color_hex": v0.get("color_hex"), "sizes": rows, "status": "active", "notes": "",
                                                   "sku_convention": "ssot", "created_by": (user or {}).get("id", "system"),
                                                   "created_by_name": (user or {}).get("name", "master_sync"), "created_at": _now(), "updated_at": _now()})
            rnd_variants += 1
    report["rnd"] = {"styles_created": created, "styles_updated": updated, "rnd_variants_created": rnd_variants,
                     "styles_code_fixed": code_fixed, "konflik": konflik}


async def _sync_employees(db, report: dict):
    n = 0
    async for u in db.users.find({"employee_id": {"$ne": None}}, {"_id": 0, "id": 1, "email": 1, "employee_id": 1}):
        r = await db.rahaza_employees.update_one({"id": u["employee_id"], "$or": [{"user_id": {"$ne": u["id"]}}, {"user_email": {"$ne": u["email"]}}]},
                                                 {"$set": {"user_id": u["id"], "user_email": u["email"], "updated_at": _now()}})
        n += r.modified_count
    report["employees_linked"] = n


PACKAGING_KW = ("plastik", "hangtag", "label", "kertas", "lakban", "tinta", "polybag", "karton", "dus")
TOOL_KW = ("atk", "pensil", "gunting", "alat ", "jarum", "penjepit", "bando", "jedai", "kapur", "meteran")
CUT_PANEL_CAT = ("CUT_PANEL", "Potongan / Kain Pola", 7)


def _material_category_code(m: dict) -> str | None:
    t, cn = (m.get("type") or "").lower(), (m.get("category_name") or m.get("sub_category") or "").lower()
    if t == "fg":
        return None
    if t == "fabric":
        return CUT_PANEL_CAT[0] if (m.get("code") or "").startswith("CUT-") or "potongan" in cn else "FABRIC"
    if "benang" in cn:
        return "SEWING_THREAD"
    if "kain keras" in cn or "interlining" in cn:
        return "INTERLINING"
    if any(k in cn for k in PACKAGING_KW):
        return "PACKAGING"
    if any(k in cn for k in TOOL_KW):
        return "OTHER"
    return "ACCESSORY"


async def _sync_material_categories(db, report: dict):
    if not await db.rahaza_material_categories.find_one({"code": CUT_PANEL_CAT[0]}):
        await db.rahaza_material_categories.insert_one({"id": _uid(), "code": CUT_PANEL_CAT[0], "name": CUT_PANEL_CAT[1], "order_seq": CUT_PANEL_CAT[2],
                                                        "active": True, "created_at": _now(), "updated_at": _now()})
    cats = {c["code"]: c for c in await db.rahaza_material_categories.find({}, {"_id": 0}).to_list(200)}
    n = 0
    async for m in db.rahaza_materials.find({"type": {"$ne": "fg"}, "$or": [{"category_id": None}, {"category_id": {"$exists": False}}, {"category": {"$in": [None, ""]}}]},
                                            {"_id": 0, "id": 1, "type": 1, "code": 1, "category_name": 1, "sub_category": 1}):
        code = _material_category_code(m)
        cat = cats.get(code)
        if not cat:
            continue
        patch = {"category_id": cat["id"], "category": cat["id"], "category_code": cat["code"], "updated_at": _now()}
        free = (m.get("category_name") or "").strip()
        if free and free.lower() != cat["name"].lower() and not m.get("sub_category"):
            patch["sub_category"] = free
        patch["category_name"] = cat["name"]
        await db.rahaza_materials.update_one({"id": m["id"]}, {"$set": patch})
        n += 1
    report["materials_categorized"] = n


async def _sync_units(db, report: dict):
    have = {u["code"] for u in await db.wh_unit_master.find({}, {"_id": 0, "code": 1}).to_list(500)}
    used = set()
    for field in ("unit", "pack_unit", "purchase_uom", "issue_uom", "display_uom"):
        used |= {u for u in await db.rahaza_materials.distinct(field) if u}
    names = {"pack": "Pack", "roll": "Roll", "pcs": "Pieces", "lusin": "Lusin", "kodi": "Kodi", "box": "Box", "set": "Set", "lembar": "Lembar"}
    added = []
    for code in sorted(used - have):
        await db.wh_unit_master.insert_one({"id": _uid(), "code": code, "name": names.get(code, code.title()), "category": "count", "symbol": code,
                                            "is_base": False, "notes": "ditambahkan otomatis: dipakai material (master_sync)", "active": True, "created_at": _now()})
        added.append(code)
    report["units_added"] = added


DEFAULT_SHIFT = {"code": "REG", "name": "Reguler 08:00–16:00", "start_time": "08:00", "end_time": "16:00"}


async def _sync_shift_default(db, report: dict):
    """Owner 2026-09-12: semua karyawan default shift 08.00–16.00 (bisa diubah per orang di HR → Shift)."""
    sh = await db.rahaza_shifts.find_one({"start_time": "08:00", "end_time": "16:00", "active": True}, {"_id": 0})
    if not sh:
        sh = {"id": _uid(), **DEFAULT_SHIFT, "active": True, "is_default": True, "created_at": _now(), "updated_at": _now()}
        await db.rahaza_shifts.insert_one(dict(sh))
    r = await db.rahaza_employees.update_many({"active": {"$ne": False}, "$or": [{"shift_id": None}, {"shift_id": {"$exists": False}}, {"shift_id": ""}]},
                                              {"$set": {"shift_id": sh["id"], "shift_code": sh["code"], "updated_at": _now()}})
    report["employees_shift_defaulted"] = r.modified_count


async def _sync_creator_passwords(db, report: dict):
    """Kreator KOL impor tanpa sandi → sandi awal sama dgn akun karyawan impor (MASTER_IMPORT_INITIAL_PASSWORD) + wajib ganti."""
    import os
    from auth import hash_password
    pwd = os.environ.get("MASTER_IMPORT_INITIAL_PASSWORD") or "Dewi@123"
    n = 0
    async for k in db.marketing_kol_creators.find({"login_email": {"$nin": [None, ""]}, "$or": [{"login_password_hash": {"$in": [None, ""]}}, {"login_password_hash": {"$exists": False}}]}, {"_id": 0, "id": 1}):
        await db.marketing_kol_creators.update_one({"id": k["id"]}, {"$set": {"login_password_hash": hash_password(pwd), "must_change_password": True, "password_set_by": "master_sync", "updated_at": _now()}})
        n += 1
    report["creator_passwords_set"] = n


async def sync_product_masters(db, user: dict | None = None) -> dict:
    report: dict = {}
    await _sync_shift_default(db, report)
    await _sync_creator_passwords(db, report)
    await _sync_material_categories(db, report)
    await _sync_units(db, report)
    by_key, bom_keys = await _sync_variants(db, report, user)
    await _sync_rnd_styles(db, report, by_key, bom_keys, user)
    await _sync_employees(db, report)
    return report
