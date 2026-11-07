"""core/material_issue_engine.py — SATU MESIN "KELUARKAN MATERIAL DARI GUDANG".

MENGAPA MODUL INI ADA (FASE H-1, 2026-08-15)
--------------------------------------------
Keluhan pemilik: *"kirim material ke cmt — bahan dikirimkan dan berkurang, tidak
perlu ada ketik ketik lagi, otomatis terbuat dan langsung berkurang saja,
begitupun aksesoris dan lainnya."*

Yang DIUKUR sebelum modul ini dibuat:
  · `POST /api/vendor-shipments` ("Kirim Material CMT") HANYA menulis
    `vendor_shipments` + `vendor_shipment_items`. Baris itemnya adalah **PO ITEM
    GARMEN** (`sku`, `size`, `color`, `qty_sent`) — tidak ada satu pun baris
    kain/aksesoris. Tidak ada mutasi `rahaza_material_stock`, tidak ada
    `rahaza_material_issues`, tidak ada jurnal.
    ⇒ kain & aksesoris keluar gudang ke CMT TANPA JEJAK; stok tidak pernah turun.
  · Layar "Pengeluaran Material" (`RahazaMaterialIssueModule`) tidak punya jalur
    CREATE sama sekali — hanya bisa meng-approve dokumen yang tidak pernah ada.
  · Satu-satunya pembuat MI dari UI memakai endpoint maklon yang sudah ditandai
    `deprecated=True`.

KEPUTUSAN DESAIN
----------------
1. TIDAK membuat mekanisme potong stok BARU. `issue_material_issue()` di bawah
   adalah inti `POST /material-issues/{id}/approve` yang DIEKSTRAK, sehingga
   "mengeluarkan material" punya SATU definisi: validasi stok per lokasi →
   `core.stock_service.issue()` (atomik, anti-race) → catat movement → posting GL
   `post_inventory_issue`. Kalau rumusnya berubah, dua-duanya ikut berubah.
   (Pelajaran Fase E: dua definisi untuk satu pertanyaan = angka bercabang.)
2. Kebutuhan material dihitung dari BOM aktif per (model, size) × qty dikirim,
   memakai konversi satuan SSOT `core.bom_uom` supaya "gram" tidak diperlakukan
   sebagai "kg".
3. Lokasi TIDAK diketik pemakai. Untuk setiap material dipilih lokasi dengan
   stok tersedia TERBANYAK — itu yang membuat alurnya "tanpa ketik-ketik".
4. Stok kurang ⇒ pengiriman DITOLAK dengan pesan yang menyebut angkanya
   (keputusan pemilik: jangan diteruskan menjadi stok minus).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MaterialShortage(Exception):
    """Stok material tidak cukup — pengiriman harus DITOLAK, bukan diteruskan."""

    def __init__(self, shortages: list):
        self.shortages = shortages
        lines = "; ".join(
            f"{s['material_code']} butuh {s['required']:g} {s.get('unit', '')} "
            f"tersedia {s['available']:g}" for s in shortages)
        super().__init__(f"Stok material tidak cukup: {lines}")


class BomMissing(Exception):
    """BOM tidak bisa dipakai — jangan menebak isi kiriman material."""


class AlreadyProcessing(Exception):
    """MI sedang/sudah dikeluarkan oleh permintaan lain (klik ganda / dua penyetuju) → HTTP 409."""


# 2026-11-06 (Tahap 1): status sementara selama stok MI dipotong. Klaim atomik status lama → issuing
# SEBELUM stok disentuh; permintaan kedua tidak lolos klaim, jadi stok & jurnal tidak terpotong dua kali.
MI_CLAIM_STATUS = "issuing"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 1. INTI PENGELUARAN (dipakai approve MI DAN kirim material ke CMT)
# ═════════════════════════════════════════════════════════════════════════════
async def issue_material_issue(db, mi: dict, user: dict, *, loc_overrides: dict | None = None,
                               ref_type: str | None = None) -> dict:
    """Keluarkan seluruh baris MI dari gudang. SATU definisi untuk semua pemanggil.

    Mengembalikan dict berisi dokumen MI terbaru + hasil posting GL.
    Melempar `MaterialShortage` bila ada baris yang stoknya kurang (TIDAK ADA
    baris yang dipotong bila salah satu kurang — semua atau tidak sama sekali).
    """
    from core import stock_service
    from routes.rahaza_inventory_shared import _enrich_mi, _log_movement, _now
    from routes.rahaza_posting import post_inventory_issue

    loc_overrides = loc_overrides or {}
    raw_items = list(mi.get("items") or [])
    default_ref = ref_type or ("wo_issue" if mi.get("work_order_id") else "manual_issue")

    # ── (a) kumpulkan pasangan (material, lokasi) lalu baca stoknya sekali ──
    pairs = set()
    for it in raw_items:
        loc = loc_overrides.get(it["material_id"]) or it.get("location_id")
        if loc and _f(it.get("qty_required")) > 0:
            pairs.add((it["material_id"], loc))
    stock_map = {}
    if pairs:
        mids = list({p[0] for p in pairs})
        locs = list({p[1] for p in pairs})
        async for s in db.rahaza_material_stock.find(
                {"material_id": {"$in": mids}, "location_id": {"$in": locs}}):
            stock_map[(s.get("material_id"), s.get("location_id"))] = s

    # ── (b) rencana + deteksi kekurangan SEBELUM memotong apa pun ──────────
    from core import negative_stock
    neg_ok = await negative_stock.allowed(db)
    plan, shortages, no_loc = [], [], []
    mat_meta = {}
    async for m in db.rahaza_materials.find(
            {"id": {"$in": [i["material_id"] for i in raw_items]}},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "type": 1}):
        mat_meta[m["id"]] = m
    loc_meta = {}
    for it in raw_items:
        loc = loc_overrides.get(it["material_id"]) or it.get("location_id")
        qty = _f(it.get("qty_required"))
        if qty <= 0:
            continue
        meta = mat_meta.get(it["material_id"], {})
        if not loc and neg_ok:
            fb = await negative_stock.fallback_location(db, meta)
            if fb:
                loc = fb["id"]
                loc_overrides[it["material_id"]] = loc
                loc_meta[loc] = fb
        if not loc:
            no_loc.append(meta.get("code") or it["material_id"])
            continue
        if neg_ok and loc not in loc_meta:
            loc_meta[loc] = await db.rahaza_locations.find_one({"id": loc}, {"_id": 0})
        srow = stock_map.get((it["material_id"], loc))
        if srow is None and neg_ok:
            srow = await db.rahaza_material_stock.find_one(
                {"material_id": it["material_id"], "location_id": loc}, {"_id": 0, "qty": 1})
        avail = _f((srow or {}).get("qty"))
        if avail + 1e-9 < qty:
            shortages.append({
                "material_id": it["material_id"],
                "material_code": meta.get("code") or it["material_id"],
                "material_name": meta.get("name") or "",
                "unit": meta.get("unit") or "",
                "required": round(qty, 4), "available": round(avail, 4),
                "location_id": loc,
            })
        plan.append({"material_id": it["material_id"], "location_id": loc,
                     "qty": qty, "item_id": it["id"]})
    if no_loc:
        raise BomMissing(
            "Material berikut tidak punya lokasi stok sama sekali di gudang: "
            + ", ".join(no_loc)
            + ". Catat penerimaan/opname dulu sebelum mengirim ke CMT.")
    if shortages and not neg_ok:
        raise MaterialShortage(shortages)
    negative_lines = shortages if neg_ok else []

    # ── (c0) 2026-11-06 (Tahap 1): KLAIM ATOMIK sebelum stok disentuh ──────
    prev_status = mi.get("status")
    if prev_status in ("issued", MI_CLAIM_STATUS):
        raise AlreadyProcessing(f"MI {mi.get('mi_number', '')} sudah/sedang dikeluarkan — muat ulang daftar.")
    claim = await db.rahaza_material_issues.update_one(
        {"id": mi["id"], "status": prev_status},
        {"$set": {"status": MI_CLAIM_STATUS, "issuing_at": _now(), "issuing_by": user.get("id")}})
    if not claim.matched_count:
        raise AlreadyProcessing(f"MI {mi.get('mi_number', '')} sedang/sudah diproses pengguna lain — "
                                "muat ulang daftar.")

    actor = {"id": str(user.get("id") or ""), "email": user.get("email", "")}
    done: list = []

    async def _rollback():
        """Kembalikan baris yang sudah terpotong pada percobaan ini + lepas klaim — supaya MI bisa
        di-approve ulang tanpa memotong baris yang sama dua kali."""
        for p in reversed(done):
            try:
                await stock_service.add(
                    p["material_id"], p["location_id"], p["qty"],
                    ref={"source": "material_issue_rollback", "mi_number": mi.get("mi_number"),
                         "item_id": p.get("item_id"), "ref_type": default_ref, "ref_id": mi["id"]},
                    actor=actor, db=db)
            except Exception:  # noqa: BLE001 — dicatat; klaim tetap dilepas
                logger.exception("pengembalian stok MI %s gagal (%s)", mi.get("mi_number"), p["material_id"])
        await db.rahaza_material_issues.update_one(
            {"id": mi["id"], "status": MI_CLAIM_STATUS},
            {"$set": {"status": prev_status, "issuing_at": None}})

    # ── (c) potong stok (atomik per baris) ────────────────────────────────
    race_failures = []
    try:
        for p in plan:
            try:
                await stock_service.issue(
                    p["material_id"], p["location_id"], p["qty"],
                    ref={"source": "material_issue", "mi_number": mi.get("mi_number"),
                         "item_id": p.get("item_id"), "ref_type": default_ref,
                         "ref_id": mi["id"]},
                    actor=actor,
                    db=db, allow_negative=neg_ok,
                    meta=negative_stock.stock_meta(mat_meta.get(p["material_id"]),
                                                   loc_meta.get(p["location_id"])) if neg_ok else None,
                )
            except stock_service.InsufficientStock:
                race_failures.append({"material_id": p["material_id"],
                                      "location_id": p["location_id"],
                                      "required": p["qty"]})
                continue
            done.append(p)
    except BaseException:
        await _rollback()
        raise
    if race_failures:
        # semua atau tidak sama sekali: baris yang sempat terpotong dikembalikan
        await _rollback()
        raise MaterialShortage([{
            "material_id": f["material_id"],
            "material_code": (mat_meta.get(f["material_id"]) or {}).get("code", "?"),
            "material_name": "", "unit": "",
            "required": f["required"], "available": 0.0,
            "location_id": f["location_id"],
        } for f in race_failures])
    for p in done:
        await _log_movement(
            db, user, type="issue", material_id=p["material_id"], qty=p["qty"],
            from_location_id=p["location_id"], to_location_id=None,
            ref_type=default_ref, ref_id=mi["id"],
            notes=f"MI {mi.get('mi_number', '')}")

    # ── (d) tutup dokumen + posting GL ────────────────────────────────────
    new_items = [{**it, "qty_issued": _f(it.get("qty_required")),
                  "location_id": loc_overrides.get(it["material_id"]) or it.get("location_id")}
                 for it in raw_items]
    await db.rahaza_material_issues.update_one(
        {"id": mi["id"]},
        {"$set": {"items": new_items, "status": "issued", "issued_at": _now(),
                  "issued_by": user.get("id"), "updated_at": _now(), "issuing_at": None,
                  "negative_stock_lines": negative_lines}})
    out = await db.rahaza_material_issues.find_one({"id": mi["id"]}, {"_id": 0})
    await _enrich_mi(db, out)
    posting = None
    try:
        posting = await post_inventory_issue(db, out, user)
    except Exception as e:  # noqa: BLE001
        logger.exception("posting jurnal pengeluaran material gagal (MI %s)",
                         mi.get("mi_number"))
        posting = {"ok": False, "error": str(e)}
    fresh = await db.rahaza_material_issues.find_one({"id": mi["id"]}, {"_id": 0})
    await _enrich_mi(db, fresh)
    fresh["_posting_result"] = posting
    return fresh


# ═════════════════════════════════════════════════════════════════════════════
# 2. KEBUTUHAN MATERIAL DARI BOM (per PO item × qty dikirim)
# ═════════════════════════════════════════════════════════════════════════════
async def _active_bom(db, model_id: str, size_id: str, color: str = ""):
    """Resolusi BOM aktif — memakai SSOT yang sama dengan MI dari job internal
    (`production_internal_adapter._active_bom`): BOM spesifik-warna → BOM umum →
    BOM apa pun untuk model+size. Sengaja TIDAK menulis resolusi sendiri supaya
    "BOM mana yang dipakai" punya satu jawaban di seluruh sistem."""
    from routes.production_internal_adapter import _active_bom as _resolve
    return await _resolve(db, model_id, size_id, color)


async def bom_need_for_lines(db, lines: list) -> tuple[dict, list, int]:
    """Hitung kebutuhan material dari BOM.

    `lines` = [{po_item_id, qty}] — qty dalam pcs garmen.
    Return (need_by_code, catatan[]) di mana need_by_code[code] = {name, unit,
    type, qty}.
    """
    from core import bom_uom
    from routes.rahaza_bom import _is_kglike

    poi_ids = [ln["po_item_id"] for ln in lines if ln.get("po_item_id")]
    po_items = {}
    if poi_ids:
        async for p in db.po_items.find({"id": {"$in": poi_ids}}, {"_id": 0}):
            po_items[p["id"]] = p

    need, notes, total_pcs = {}, [], 0
    for ln in lines:
        pi = po_items.get(ln.get("po_item_id")) or {}
        qty = int(_f(ln.get("qty")))
        if qty <= 0:
            continue
        total_pcs += qty
        model_id, size_id = pi.get("model_id"), pi.get("size_id")
        label = pi.get("sku") or pi.get("product_name") or ln.get("po_item_id")
        if not model_id or not size_id:
            notes.append(f"{label}: PO item belum tertaut model/ukuran master "
                         f"(model_id/size_id kosong) — BOM tidak bisa dibaca")
            continue
        bom = await _active_bom(db, model_id, size_id, pi.get("color") or "")
        if not bom:
            notes.append(f"{label}: tidak ada BOM aktif untuk model/ukuran ini")
            continue
        bom_mats, uom_warn = await bom_uom.ensure_uom(db, bom)
        for w in uom_warn:
            if w not in notes:
                notes.append(w)
        for m in bom_mats:
            code = (m.get("code") or "").strip().upper()
            if not code:
                continue
            base_unit = bom_uom.base_unit_of(m)
            is_kg = _is_kglike({**m, "unit": base_unit})
            e = need.setdefault(code, {
                "name": m.get("name") or code,
                "unit": base_unit or ("kg" if is_kg else "pcs"),
                "type": "yarn" if is_kg else "accessory",
                "qty": 0.0,
            })
            e["qty"] += bom_uom.qty_base_of(m) * qty
    return need, notes, total_pcs


async def best_location_for(db, material_id: str, qty_needed: float):
    """Lokasi dengan stok tersedia TERBANYAK — supaya pemakai tidak perlu memilih.

    Lokasi karantina (storage_role/role 'karantina') TIDAK pernah dipilih otomatis.
    """
    best, best_qty = None, None
    karantina = set()
    async for l in db.rahaza_locations.find(
            {"$or": [{"storage_role": "karantina"}, {"role": "karantina"}]}, {"_id": 0, "id": 1}):
        karantina.add(l["id"])
    async for s in db.rahaza_material_stock.find(
            {"material_id": material_id}, {"_id": 0, "location_id": 1, "qty": 1}):
        if s.get("location_id") in karantina:
            continue
        q = _f(s.get("qty"))
        if best_qty is None or q > best_qty:
            best, best_qty = s.get("location_id"), q
    # baris minus (mode sementara) tetap dianggap "punya lokasi", tersedia = saldo nyata
    return best, (best_qty if best_qty is not None else 0.0)


async def autofill_locations(db, items: list, default_loc: str | None = None) -> list:
    """Isi `location_id` yang kosong pada baris MI — pemakai tidak boleh dipaksa memilih.

    Urutan: lokasi bawaan yang dipilih pemakai → lokasi berstok terbanyak (bukan
    karantina) → gudang bawaan mode 'stok boleh minus' (A-* aksesoris, lainnya bahan).
    Mengembalikan daftar kode material yang lokasinya diisi otomatis.
    """
    from core import negative_stock
    karantina = {l["id"] async for l in db.rahaza_locations.find(
        {"$or": [{"storage_role": "karantina"}, {"role": "karantina"}]}, {"_id": 0, "id": 1})}
    filled = []
    for it in items or []:
        if it.get("location_id") and it["location_id"] not in karantina:
            continue
        it["location_id"] = None   # karantina bukan tempat ambil material produksi
        loc = default_loc
        if not loc:
            loc, _ = await best_location_for(db, it["material_id"], _f(it.get("qty_required")))
        if not loc:
            mat = await db.rahaza_materials.find_one({"id": it["material_id"]}, {"_id": 0, "code": 1})
            fb = await negative_stock.fallback_location(db, mat or {})
            loc = fb["id"] if fb else None
        if loc:
            it["location_id"] = loc
            filled.append(it.get("material_code") or it["material_id"])
    return filled


# ═════════════════════════════════════════════════════════════════════════════
# 3. KIRIM MATERIAL KE CMT ⇒ MI OTOMATIS + STOK BERKURANG
# ═════════════════════════════════════════════════════════════════════════════
async def issue_for_vendor_shipment(db, shipment: dict, ship_items: list,
                                    user: dict) -> dict:
    """Terbitkan Material Issue OTOMATIS untuk satu surat jalan material ke CMT.

    Idempoten: bila surat jalan ini sudah punya MI, dokumen itu yang dikembalikan.
    """
    from routes.rahaza_inventory_shared import _uid, _gen_mi_number, _now

    existing = await db.rahaza_material_issues.find_one(
        {"vendor_shipment_id": shipment["id"], "status": {"$ne": "rejected"}}, {"_id": 0})
    if existing:
        return {"ok": True, "already": True, "mi": existing}
    # 2026-11-06 (Tahap 2): surat jalan yang seluruh kebutuhannya sudah tertutup permintaan aksesoris
    sdoc = await db.vendor_shipments.find_one({"id": shipment["id"]}, {"_id": 0, "material_issue_skipped": 1})
    if (sdoc or {}).get("material_issue_skipped"):
        return {"ok": True, "already": True, "skipped": True, "mi": None}

    lines = [{"po_item_id": it.get("po_item_id"), "qty": it.get("qty_sent")}
             for it in ship_items if it.get("po_item_id")]
    need, notes, total_pcs = await bom_need_for_lines(db, lines)
    if not need:
        raise BomMissing(
            "Kebutuhan material tidak bisa dihitung dari BOM, jadi tidak ada yang "
            "dikeluarkan dari gudang. Penyebab: "
            + ("; ".join(notes) if notes else "BOM kosong")
            + ". Lengkapi BOM model/ukuran di Master Produk lalu kirim ulang.")

    # ── resolve master material by code (JANGAN membuat master baru di sini:
    #    material yang tidak ada di master berarti BOM menunjuk barang yang tidak
    #    pernah masuk gudang — itu harus terlihat, bukan ditambal diam-diam) ──
    codes = list(need.keys())
    mats = {}
    async for m in db.rahaza_materials.find(
            {"code": {"$in": codes}, "active": True}, {"_id": 0}):
        mats[m["code"]] = m
    unknown = [c for c in codes if c not in mats]
    if unknown:
        raise BomMissing(
            "Material pada BOM belum ada di Master Item gudang: "
            + ", ".join(unknown)
            + ". Daftarkan materialnya (atau perbaiki kode di BOM) sebelum "
              "mengirim material ke CMT.")

    from core import negative_stock
    neg_ok = await negative_stock.allowed(db)
    items, auto_loc, no_stock, neg_notes = [], {}, [], []
    for code, e in need.items():
        mat = mats[code]
        loc, avail = await best_location_for(db, mat["id"], e["qty"])
        if not loc and neg_ok:
            fb = await negative_stock.fallback_location(db, mat)
            if fb:
                loc, avail = fb["id"], 0.0
                neg_notes.append(f"{code} belum ada baris stok → dibuat minus di {fb.get('code')}")
        if not loc:
            no_stock.append(f"{code} ({e['qty']:g} {e['unit']})")
            continue
        auto_loc[mat["id"]] = loc
        items.append({
            "id": _uid(), "material_id": mat["id"],
            "qty_required": round(e["qty"], 4),
            "qty_issued": 0, "location_id": loc, "notes": "",
        })
    if no_stock:
        raise BomMissing(
            "Material berikut belum punya baris stok di gudang mana pun: "
            + ", ".join(no_stock)
            + ". Catat penerimaan barang atau opname dulu.")
    if neg_notes:
        notes = list(notes) + neg_notes

    # 2026-11-06 (Tahap 2) — SATU KELUAR PER KEBUTUHAN PO: aksesoris yang sudah dikeluarkan untuk PO
    # ini lewat permintaan aksesoris / Keluar manual ber-PO dikurangkan dari kiriman ini (dulu
    # dikeluarkan lagi: butuh 100 → keluar 140). Bagian yang dipakai dicatat di surat jalan supaya
    # tidak dikurangkan dua kali oleh surat jalan berikutnya.
    offsets: list = []
    po_id = shipment.get("po_id")
    if po_id:
        from core.accessory_issue import request_credit_for_po
        credit = await request_credit_for_po(db, po_id)
        for it in items:
            c = _f(credit.get(it["material_id"]))
            if c <= 1e-9:
                continue
            off = round(min(c, _f(it["qty_required"])), 4)
            it["qty_required"] = round(_f(it["qty_required"]) - off, 4)
            it["offset_request_qty"] = off
            credit[it["material_id"]] = c - off
            offsets.append({"material_id": it["material_id"], "qty": off})
        if offsets:
            notes = list(notes) + [f"{len(offsets)} aksesoris dikurangi karena sudah keluar lewat permintaan aksesoris PO ini"]
        items = [it for it in items if _f(it["qty_required"]) > 1e-9]
        if not items:
            await db.vendor_shipments.update_one({"id": shipment["id"]}, {"$set": {
                "accessory_request_offsets": offsets, "material_issue_skipped": True}})
            return {"ok": True, "already": False, "skipped": True, "mi": None, "bom_notes": notes,
                    "total_pcs": total_pcs, "material_lines": 0, "request_offsets": offsets}

    mi = {
        "id": _uid(),
        "mi_number": await _gen_mi_number(db),
        "work_order_id": None,
        "wo_number_snapshot": "",
        "job_id": None,
        "vendor_shipment_id": shipment["id"],
        "vendor_shipment_number": shipment.get("shipment_number", ""),
        "vendor_id": shipment.get("vendor_id", ""),
        "vendor_name": shipment.get("vendor_name", ""),
        "production_po_id": shipment.get("po_id"),
        "po_number_snapshot": shipment.get("po_number", ""),
        "qty_wo_pcs": total_pcs,
        "items": items,
        "status": "pending_approval",
        "source": "vendor_shipment",
        "notes": ("Otomatis dari Kirim Material CMT "
                  f"{shipment.get('shipment_number', '')} (FASE H-1)"
                  + (f" · catatan BOM: {'; '.join(notes)}" if notes else "")),
        "bom_notes": notes,
        "created_by": user.get("id"), "created_by_name": user.get("name", ""),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_material_issues.insert_one(dict(mi))
    fresh = await issue_material_issue(db, mi, user, loc_overrides=auto_loc,
                                       ref_type="cmt_material_issue")
    await db.vendor_shipments.update_one(
        {"id": shipment["id"]},
        {"$set": {"material_issue_id": mi["id"],
                  "material_issue_number": mi["mi_number"],
                  **({"accessory_request_offsets": offsets} if offsets else {})}})
    return {"ok": True, "already": False, "mi": fresh,
            "mi_number": mi["mi_number"], "bom_notes": notes,
            "negative_stock_lines": fresh.get("negative_stock_lines") or [],
            "total_pcs": total_pcs, "material_lines": len(items)}


# ═════════════════════════════════════════════════════════════════════════════
# 4. KIRIM MATERIAL MAKLON ⇒ MI HANYA UNTUK AKSESORIS MILIK DA (2026-11-02, K14 / P-7)
# ═════════════════════════════════════════════════════════════════════════════
# Keputusan owner K14 (P-7): kain/bahan milik KLIEN maklon di luar neraca DA (tidak di-MI), tetapi
# aksesoris MILIK DA yang dipakai pesanan maklon tetap dibukukan sebagai BIAYA DA lewat MI. Dulu
# `routes/vendor_shipment.py` mengecualikan SEMUA surat jalan maklon dari MI, sehingga stok aksesoris
# DA tidak pernah turun dan biayanya tidak terbukukan (dilaporkan sebagai celah oleh
# `production_maklon_bridge.compute_maklon_hpp`). Sumber kebutuhan = BOM maklon per PO
# (`dewi_maklon_bom.materials`, baris `ownership` milik DA + `material_id`), mesin potong stok &
# posting = SAMA (`issue_material_issue`); jurnalnya Dr biaya proyek maklon / Cr 1-1402.
MAKLON_DA_OWNERSHIP = ("cv_da_stock", "cv_da", "da_provided")   # sama dgn production_maklon_bridge
_MI_NOT_COUNTED = ("rejected", "draft", "cancelled")


def maklon_da_need(bom_lines: list, pcs_total: float, issued_by_mat: dict) -> tuple[list, list]:
    """Fungsi murni: kebutuhan MI per baris BOM maklon milik DA.

    need = qty_per_pcs × pcs KUMULATIF semua surat jalan PO ini − qty yang SUDAH di-MI untuk PO
    ini (jalur mana pun). Kumulatif = tidak dobel bila MI sudah diterbitkan lewat jalur lain.
    Return (baris [{material_id, qty, bom_unit, name}], catatan)."""
    out, notes = [], []
    agg: dict = {}
    for ln in bom_lines or []:
        if (ln.get("ownership") or "") not in MAKLON_DA_OWNERSHIP:
            continue                                   # kain/bahan milik klien — bukan stok DA
        name = ln.get("material_name") or ln.get("material_id") or "?"
        if not ln.get("material_id"):
            notes.append(f"{name}: baris BOM maklon milik DA tanpa material_id — tidak bisa di-MI")
            continue
        per = _f(ln.get("qty_per_pcs"))
        if per <= 0:
            notes.append(f"{name}: qty per pcs 0 di BOM maklon — dilewati")
            continue
        a = agg.setdefault(ln["material_id"], {"material_id": ln["material_id"], "per_pcs": 0.0,
                                               "bom_unit": ln.get("unit") or "", "name": name})
        a["per_pcs"] += per
    for mid, a in agg.items():
        need = round(a["per_pcs"] * _f(pcs_total) - _f(issued_by_mat.get(mid)), 4)
        if need > 1e-9:
            out.append({"material_id": mid, "qty": need, "bom_unit": a["bom_unit"], "name": a["name"]})
    return out, notes


async def issue_for_maklon_shipment(db, shipment: dict, ship_items: list, user: dict) -> dict | None:
    """MI OTOMATIS aksesoris DA untuk satu surat jalan material MAKLON. None = tidak ada yang di-MI
    (BOM maklon tanpa aksesoris DA, atau kebutuhan sudah tertutup MI lain). Idempoten per surat jalan."""
    # Tahap 8 fase 2 (TODO): jurnal pengeluaran ini masih di buku DA (stok milik DA). Fase 2 menambah pasangan
    # antar CV (DA menjual aksesoris ke CV Sukma dengan margin yang bisa diatur, bawaan 0%).
    from core import bom_uom
    from core import uom as uom_core
    from routes.rahaza_inventory_shared import _gen_mi_number, _now, _uid

    existing = await db.rahaza_material_issues.find_one(
        {"vendor_shipment_id": shipment["id"], "status": {"$ne": "rejected"}}, {"_id": 0})
    if existing:
        return {"ok": True, "already": True, "mi": existing}
    po_id = shipment.get("po_id")
    bom = await db.dewi_maklon_bom.find_one({"po_id": po_id}, {"_id": 0}) if po_id else None
    if not bom or not any((m.get("ownership") or "") in MAKLON_DA_OWNERSHIP for m in bom.get("materials") or []):
        return None

    # pcs kumulatif semua surat jalan PO ini (termasuk yang baru dibuat) & qty yang sudah di-MI
    sids = [s["id"] async for s in db.vendor_shipments.find({"po_id": po_id}, {"_id": 0, "id": 1})]
    pcs_total = 0.0
    async for si in db.vendor_shipment_items.find({"shipment_id": {"$in": sids}}, {"_id": 0, "qty_sent": 1}):
        pcs_total += _f(si.get("qty_sent"))
    # 2026-11-06 (Tahap 2): "sudah keluar" = MI PO ini + pengeluaran lewat permintaan aksesoris /
    # Keluar manual ber-PO yang sama (dulu hanya MI → permintaan untuk PO yang sama dikeluarkan lagi).
    from core.accessory_issue import po_issued_by_material
    issued = await po_issued_by_material(db, po_id)

    need, notes = maklon_da_need(bom.get("materials") or [], pcs_total, issued)
    mats = {}
    if need:
        async for m in db.rahaza_materials.find({"id": {"$in": [n["material_id"] for n in need]}}, {"_id": 0}):
            mats[m["id"]] = m
    items, auto_loc = [], {}
    from core import negative_stock
    neg_ok = await negative_stock.allowed(db)
    for n in need:
        mat = mats.get(n["material_id"])
        if not mat:
            notes.append(f"{n['name']}: material_id {n['material_id']} tidak ada di Master Item — tidak di-MI")
            continue
        qty = n["qty"]
        if n["bom_unit"] and (n["bom_unit"] or "").strip().lower() != (mat.get("unit") or "").strip().lower():
            try:
                f, _src = bom_uom.factor_to_base(mat, n["bom_unit"])
                qty = round(qty * f, 4)
            except uom_core.UomError as e:
                raise BomMissing(f"{mat.get('code') or n['name']}: satuan BOM maklon '{n['bom_unit']}' "
                                 f"tidak bisa dikonversi ke satuan master ({e}).")
        loc, _avail = await best_location_for(db, mat["id"], qty)
        if not loc and neg_ok:
            fb = await negative_stock.fallback_location(db, mat)
            loc = fb["id"] if fb else None
        if not loc:
            raise BomMissing(f"Aksesoris DA {mat.get('code') or n['name']} belum punya baris stok di gudang "
                             "mana pun. Catat penerimaan/opname dulu.")
        auto_loc[mat["id"]] = loc
        items.append({"id": _uid(), "material_id": mat["id"], "qty_required": qty,
                      "qty_issued": 0, "location_id": loc, "notes": "aksesoris DA — pesanan maklon"})
    if not items:
        return {"ok": True, "already": False, "skipped": True, "mi": None, "bom_notes": notes,
                "total_pcs": pcs_total, "material_lines": 0} if notes else None

    mi = {
        "id": _uid(), "mi_number": await _gen_mi_number(db),
        "work_order_id": None, "wo_number_snapshot": "", "job_id": None,
        "vendor_shipment_id": shipment["id"],
        "vendor_shipment_number": shipment.get("shipment_number", ""),
        "vendor_id": shipment.get("vendor_id", ""), "vendor_name": shipment.get("vendor_name", ""),
        "production_po_id": po_id, "po_number_snapshot": shipment.get("po_number", ""),
        "business_type": "maklon", "cost_target": "maklon",
        "qty_wo_pcs": int(sum(_f(i.get("qty_sent")) for i in ship_items)),
        "items": items, "status": "pending_approval", "source": "vendor_shipment_maklon",
        "notes": ("Otomatis dari Kirim Material CMT MAKLON "
                  f"{shipment.get('shipment_number', '')} — aksesoris milik DA (K14)"
                  + (f" · catatan: {'; '.join(notes)}" if notes else "")),
        "bom_notes": notes,
        "created_by": user.get("id"), "created_by_name": user.get("name", ""),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_material_issues.insert_one(dict(mi))
    fresh = await issue_material_issue(db, mi, user, loc_overrides=auto_loc, ref_type="maklon_material_issue")
    await db.vendor_shipments.update_one({"id": shipment["id"]}, {"$set": {
        "material_issue_id": mi["id"], "material_issue_number": mi["mi_number"]}})
    return {"ok": True, "already": False, "mi": fresh, "mi_number": mi["mi_number"], "bom_notes": notes,
            "negative_stock_lines": fresh.get("negative_stock_lines") or [],
            "total_pcs": pcs_total, "material_lines": len(items)}
