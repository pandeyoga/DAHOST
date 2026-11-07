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
        # baris kiriman Tahap 9 (ber-`kind`) membawa lokasinya sendiri — satu material boleh dari BANYAK lokasi
        loc = (it.get("location_id") if it.get("kind") else None) or loc_overrides.get(it["material_id"])             or it.get("location_id")
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
        loc = (it.get("location_id") if it.get("kind") else None) or loc_overrides.get(it["material_id"])             or it.get("location_id")
        qty = _f(it.get("qty_required"))
        if qty <= 0:
            continue
        # Tahap 9 (7 Nov 2026): baris ber-`allow_negative: False` (POTONGAN) tidak pernah boleh minus, juga saat
        # setelan "stok boleh minus" ON — kiriman ke CMT wajib didahului catatan cutting.
        item_neg = neg_ok and it.get("allow_negative") is not False
        meta = mat_meta.get(it["material_id"], {})
        if not loc and item_neg:
            fb = await negative_stock.fallback_location(db, meta)
            if fb:
                loc = fb["id"]
                loc_overrides[it["material_id"]] = loc
                loc_meta[loc] = fb
        if not loc:
            no_loc.append(meta.get("code") or it["material_id"])
            continue
        if item_neg and loc not in loc_meta:
            loc_meta[loc] = await db.rahaza_locations.find_one({"id": loc}, {"_id": 0})
        srow = stock_map.get((it["material_id"], loc))
        if srow is None and item_neg:
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
                "location_id": loc, "_strict": not item_neg,
            })
        plan.append({"material_id": it["material_id"], "location_id": loc,
                     "qty": qty, "item_id": it["id"], "neg": item_neg})
    if no_loc:
        raise BomMissing(
            "Material berikut tidak punya lokasi stok sama sekali di gudang: "
            + ", ".join(no_loc)
            + ". Catat penerimaan/opname dulu sebelum mengirim ke CMT.")
    strict = [{k: v for k, v in s.items() if k != "_strict"} for s in shortages if s.get("_strict")]
    if strict:
        raise MaterialShortage(strict)
    negative_lines = [{k: v for k, v in s.items() if k != "_strict"} for s in shortages if not s.get("_strict")]

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
                    db=db, allow_negative=p["neg"],
                    meta=negative_stock.stock_meta(mat_meta.get(p["material_id"]),
                                                   loc_meta.get(p["location_id"])) if p["neg"] else None,
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
                  "location_id": (it.get("location_id") if it.get("kind") else None)
                  or loc_overrides.get(it["material_id"]) or it.get("location_id")}
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
async def _active_bom(db, model_id: str, size_id: str, color: str = "", color_code: str = ""):
    """Resolusi BOM aktif — memakai SSOT yang sama dengan MI dari job internal
    (`production_internal_adapter._active_bom`): BOM spesifik-warna → BOM umum (tanpa warna).
    Tahap 9: TIDAK PERNAH jatuh ke BOM warna lain."""
    from routes.production_internal_adapter import _active_bom as _resolve
    return await _resolve(db, model_id, size_id, color, color_code=color_code)


async def bom_need_for_lines(db, lines: list) -> tuple[dict, list, int]:
    """Hitung kebutuhan material dari BOM.

    `lines` = [{po_item_id, qty}] — qty dalam pcs garmen.
    Return (need_by_code, catatan[]) di mana need_by_code[code] = {name, unit,
    type, qty}.
    """
    from core import bom_uom
    from core.kirim_cmt import kind_of as kirim_kind
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
        bom = await _active_bom(db, model_id, size_id, pi.get("color") or "", pi.get("color_code") or "")
        if not bom:
            notes.append(f"{label}: tidak ada BOM aktif untuk warna/model/ukuran ini")
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
            # Tahap 9: potongan (hasil Cutting) BUKAN aksesoris — dulu semua yang bukan kg disebut "accessory"
            kind = kirim_kind(line=m)
            e = need.setdefault(code, {
                "name": m.get("name") or code,
                "unit": base_unit or ("kg" if is_kg else "pcs"),
                "type": "yarn" if is_kg else ("cut_panel" if kind == "potongan" else "accessory"),
                "kind": kind,
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
# 3. KIRIM KE CMT ⇒ SATU MI + STOK BERKURANG (Tahap 9: satu hitungan `core.kirim_cmt`)
# ═════════════════════════════════════════════════════════════════════════════
# Tahap 9 (7 Nov 2026): dua jalur lama (`issue_for_vendor_shipment` = BOM × qty dengan pecahan 4 desimal,
# `issue_for_maklon_shipment` = BOM maklon kumulatif) DIGANTI satu hitungan `core.kirim_cmt.compute`:
# potongan pas per SKU dari BOM (wajib cukup), aksesoris = jumlah FINAL user dalam satuan serah. Nama fungsi
# dipertahankan karena dipanggil route kiriman & uji; keduanya memakai mesin yang sama.
MAKLON_DA_OWNERSHIP = ("cv_da_stock", "cv_da", "da_provided")   # sama dgn production_maklon_bridge
_MI_NOT_COUNTED = ("rejected", "draft", "cancelled")


async def issue_for_vendor_shipment(db, shipment: dict, ship_items: list, user: dict, *,
                                    accessory_input=None, materials=None, mode: str = "normal") -> dict:
    """Kiriman ke CMT (PO internal maupun maklon) → hitungan `core.kirim_cmt` → satu MI → stok berkurang.

    Melempar `core.kirim_cmt.KirimBlocked` (turunan `BomMissing`) bila potongan kurang / BOM warna tidak ada,
    dan `MaterialShortage` bila stok berubah di tengah jalan. Idempoten per kiriman."""
    from core import kirim_cmt
    return await kirim_cmt.issue_for_shipment(db, shipment, ship_items, user, accessory_input=accessory_input,
                                              materials=materials, mode=mode)


async def issue_for_maklon_shipment(db, shipment: dict, ship_items: list, user: dict, *,
                                    accessory_input=None, materials=None, mode: str = "normal") -> dict:
    """PO maklon: SAMA dengan `issue_for_vendor_shipment` — hitungan membaca jenis PO sendiri (kain & potongan
    milik klien tidak dikeluarkan; aksesoris milik DA keluar sesuai jumlah serah, `cost_target='maklon'`)."""
    return await issue_for_vendor_shipment(db, shipment, ship_items, user, accessory_input=accessory_input,
                                           materials=materials, mode=mode)
