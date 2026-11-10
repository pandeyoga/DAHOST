"""core.kirim_permintaan — "Permintaan tambahan" ke CMT: SATU daftar, satu jalan keluar (Tahap 9, keputusan 12).

Dulu ada dua permukaan untuk hal yang sama:
  * `material_requests` (Permintaan Tambahan / Pengganti dari Portal Vendor) — disetujui → surat jalan anak,
    TETAPI stok tidak berkurang (`exceptions.py`, contoh SHP-202609-0002-A1 16 pcs);
  * `dewi_cmt_component_requests` (menu "Komponen Kurang", input staf + otomatis dari pemeriksaan vendor) —
    "Terkirim" memotong stok tanpa surat jalan.
Keputusan owner: satu tab "Permintaan tambahan" di Kirim ke CMT. Setelah DISETUJUI, permintaan menjadi KIRIMAN
TAMBAHAN yang mengurangi stok lewat hitungan yang SAMA dengan kiriman biasa (`core.kirim_cmt`). Endpoint lama
(`PUT /material-requests/{id}`, `POST /dewi/cmt-component-requests/{id}/set-status`) mendelegasikan ke sini.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.helpers import new_id, now

logger = logging.getLogger(__name__)

SRC_VENDOR = "mr"        # material_requests
SRC_STAF = "krg"         # dewi_cmt_component_requests
STATUS_LABEL = {"menunggu": "Menunggu", "dikirim": "Sudah dikirim", "ditolak": "Ditolak"}
_MR_STATUS = {"Pending": "menunggu", "Approved": "dikirim", "Rejected": "ditolak"}
_KRG_STATUS = {"pending": "menunggu", "cutting": "menunggu", "ready": "menunggu", "delivered": "dikirim",
               "rejected": "ditolak", "cancelled": "ditolak"}
_KRG_SUB = {"pending": "Menunggu", "cutting": "Sedang dipotong", "ready": "Siap kirim"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def bt_query(business_type: Optional[str]) -> dict:
    """Saringan jenis PO (aturan Tahap 9): internal = 'internal'; maklon = bukan internal."""
    if business_type == "internal":
        return {"business_type": "internal"}
    if business_type == "maklon":
        return {"business_type": {"$ne": "internal"}}
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# 1. DAFTAR GABUNGAN
# ═════════════════════════════════════════════════════════════════════════════
def _mr_row(d: dict) -> dict:
    items = d.get("items") or []
    acc = d.get("accessory_items_sent") or []
    kind = "Pengganti" if d.get("request_type") == "REPLACEMENT" else "Tambahan"
    return {
        "key": f"{SRC_VENDOR}:{d['id']}", "src": SRC_VENDOR, "id": d["id"],
        "source": "vendor", "source_label": "Portal vendor" if not d.get("staff_override") else "Atas nama vendor",
        "kind_label": kind, "number": d.get("request_number") or "", "vendor_id": d.get("vendor_id") or "",
        "vendor_name": d.get("vendor_name") or "", "po_id": d.get("po_id") or "", "po_number": d.get("po_number") or "",
        "shipment_number": d.get("original_shipment_number") or "",
        "summary": ", ".join(f"{i.get('sku') or i.get('product_name') or '?'} {int(_f(i.get('requested_qty')))} pcs"
                             for i in items[:4]) + (f" +{len(items) - 4}" if len(items) > 4 else ""),
        "total_pcs": int(sum(_f(i.get("requested_qty")) for i in items)), "accessory_lines": len(acc),
        "status": _MR_STATUS.get(d.get("status"), "menunggu"), "sub_status": "",
        "child_shipment_id": d.get("child_shipment_id") or "", "child_shipment_number": d.get("child_shipment_number") or "",
        "material_issue_number": d.get("material_issue_number") or "",
        "reason": d.get("reason") or "", "admin_notes": d.get("admin_notes") or "",
        "business_type": d.get("business_type") or "", "created_at": d.get("created_at"),
    }


def _krg_row(d: dict, po_bt: dict) -> dict:
    items = d.get("items") or []
    lines = d.get("garment_lines") or []
    st = d.get("status") or "pending"
    origin = d.get("origin") or "manual"
    return {
        "key": f"{SRC_STAF}:{d['id']}", "src": SRC_STAF, "id": d["id"],
        "source": "pemeriksaan" if origin == "vendor_inspection" else "staf",
        "source_label": "Hasil pemeriksaan vendor" if origin == "vendor_inspection" else "Input staf",
        "kind_label": "Aksesoris" if d.get("request_type") == "accessory" else "Komponen",
        "number": d.get("request_code") or "", "vendor_id": d.get("vendor_id") or d.get("cmt_partner_id") or "",
        "vendor_name": d.get("vendor_name") or d.get("cmt_partner_name") or "",
        "po_id": d.get("po_id") or "", "po_number": d.get("po_number") or "",
        "shipment_number": d.get("source_shipment_number") or "",
        "summary": ", ".join([f"{x.get('sku') or '?'} {int(_f(x.get('qty')))} pcs" for x in lines[:3]]
                             + [f"{i.get('material_code') or i.get('component_type') or '?'} "
                                f"{_f(i.get('qty')):g} {i.get('unit_label') or i.get('unit') or ''}".strip()
                                for i in items[:3]]),
        "total_pcs": int(sum(_f(x.get("qty")) for x in lines)), "accessory_lines": len(items),
        "status": _KRG_STATUS.get(st, "menunggu"), "sub_status": _KRG_SUB.get(st, ""),
        "child_shipment_id": d.get("fulfilled_shipment_id") or "",
        "child_shipment_number": d.get("fulfilled_shipment_number") or "",
        "material_issue_number": d.get("material_issue_number") or "",
        "reason": d.get("notes") or "", "admin_notes": d.get("rejection_reason") or "",
        "status_note": d.get("status_note") or "",
        "business_type": po_bt.get(d.get("po_id"), ""), "created_at": d.get("created_at"),
    }


def _ts(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v or "")


async def list_requests(db, *, business_type: Optional[str] = None, status: str = "", source: str = "",
                        search: str = "", vendor_id: str = "", scope: Optional[dict] = None) -> list:
    """Gabungan dua sumber, terbaru dulu. `scope` = saringan vendor (portal vendor / mode atas nama vendor)."""
    rows: list = []
    q_mr = {**bt_query(business_type), **(scope or {})}
    if vendor_id:
        q_mr["vendor_id"] = vendor_id
    if source in ("", "vendor"):
        for d in await db.material_requests.find(q_mr, {"_id": 0}).sort("created_at", -1).to_list(1000):
            rows.append(_mr_row(d))
    if source in ("", "staf", "pemeriksaan"):
        po_bt = {}
        q_k: dict = {}
        if business_type in ("internal", "maklon"):
            pos = await db.production_pos.find(bt_query(business_type), {"_id": 0, "id": 1, "business_type": 1}
                                               ).to_list(5000)
            po_bt = {p["id"]: p.get("business_type") or "" for p in pos}
            q_k["po_id"] = {"$in": list(po_bt)}
        if vendor_id or (scope or {}).get("vendor_id"):
            vid = vendor_id or scope["vendor_id"]
            q_k["$or"] = [{"vendor_id": vid}, {"cmt_partner_id": vid}]
        docs = await db.dewi_cmt_component_requests.find(q_k, {"_id": 0}).sort("created_at", -1).to_list(1000)
        if not po_bt:
            ids = sorted({d.get("po_id") for d in docs if d.get("po_id")})
            po_bt = {p["id"]: p.get("business_type") or "" for p in await db.production_pos.find(
                {"id": {"$in": ids}}, {"_id": 0, "id": 1, "business_type": 1}).to_list(5000)} if ids else {}
        for d in docs:
            r = _krg_row(d, po_bt)
            if source and r["source"] != source:
                continue
            rows.append(r)
    if status:
        rows = [r for r in rows if r["status"] == status]
    s = (search or "").strip().lower()
    if s:
        rows = [r for r in rows if any(s in str(r.get(k) or "").lower() for k in
                                       ("number", "vendor_name", "po_number", "shipment_number", "summary"))]
    rows.sort(key=lambda r: _ts(r.get("created_at")), reverse=True)
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# 2. ISI PERMINTAAN → baris hitungan kiriman
# ═════════════════════════════════════════════════════════════════════════════
async def request_payload(db, src: str, doc: dict, accessory_override: Optional[list] = None) -> dict:
    """{po_id, vendor_id, parent_id, lines[{po_item_id, qty, sku…}], materials[{material_id, qty, uom}]}"""
    if src == SRC_VENDOR:
        lines = [{"po_item_id": i.get("po_item_id"), "qty": _f(i.get("requested_qty")), "sku": i.get("sku") or "",
                  "product_name": i.get("product_name") or "", "size": i.get("size") or "", "color": i.get("color") or "",
                  "serial_number": i.get("serial_number") or ""}
                 for i in doc.get("items") or [] if i.get("po_item_id") and _f(i.get("requested_qty")) > 0]
        mats = []
        if doc.get("category") == "accessories":
            lines = []
            mats = [{"material_id": i.get("accessory_id"), "qty": _f(i.get("requested_qty")), "uom": i.get("unit") or ""}
                    for i in doc.get("items") or []]
        else:
            if accessory_override is not None:
                acc = accessory_override
            else:
                from routes.exceptions import _accessory_shortages_for_request
                acc = await _accessory_shortages_for_request(db, doc)
            mats = [{"material_id": a.get("accessory_id") or a.get("material_id"),
                     "qty": _f(a.get("qty_sent", a.get("missing_qty"))), "uom": a.get("unit") or ""}
                    for a in acc or [] if _f(a.get("qty_sent", a.get("missing_qty"))) > 0]
        orig = await db.vendor_shipments.find_one({"id": doc.get("original_shipment_id")}, {"_id": 0}) or {}
        return {"po_id": doc.get("po_id") or orig.get("po_id") or "", "vendor_id": doc.get("vendor_id") or orig.get("vendor_id"),
                "parent_id": doc.get("original_shipment_id") or "", "lines": lines,
                "materials": [m for m in mats if m.get("material_id") and m["qty"] > 0]}
    lines = [{"po_item_id": x.get("po_item_id"), "qty": _f(x.get("qty")), "sku": x.get("sku") or "",
              "product_name": x.get("product_name") or "", "size": x.get("size") or "", "color": x.get("color") or ""}
             for x in doc.get("garment_lines") or [] if x.get("po_item_id") and _f(x.get("qty")) > 0]
    mats = [{"material_id": i.get("material_id"), "qty": _f(i.get("qty")), "uom": i.get("handover_uom") or i.get("unit")
             or "", "material_code": i.get("material_code") or i.get("component_type") or ""}
            for i in doc.get("items") or [] if _f(i.get("qty")) > 0]
    return {"po_id": doc.get("po_id") or "", "vendor_id": doc.get("vendor_id") or doc.get("cmt_partner_id") or "",
            "parent_id": doc.get("source_shipment_id") or "", "lines": lines, "materials": mats}


async def preview(db, src: str, doc: dict, accessory_override: Optional[list] = None) -> dict:
    from core import kirim_cmt
    p = await request_payload(db, src, doc, accessory_override)
    if not p["po_id"]:
        return {"applicable": False, "blocking": True, "potongan": [], "aksesoris": [], "warnings": [],
                "blocking_reasons": ["Permintaan belum menunjuk PO — pilih PO-nya dulu."]}
    if any(not m.get("material_id") for m in p["materials"]):
        return {"applicable": False, "blocking": True, "potongan": [], "aksesoris": [], "warnings": [],
                "blocking_reasons": ["Ada baris tanpa barang dari master material — ubah permintaan dulu."]}
    return await kirim_cmt.compute(db, po_id=p["po_id"], lines=p["lines"], materials=p["materials"], mode="tambahan")


# ═════════════════════════════════════════════════════════════════════════════
# 3. SETUJUI = KIRIMAN TAMBAHAN YANG MENGURANGI STOK
# ═════════════════════════════════════════════════════════════════════════════
async def _child_number(db, parent: dict, stype: str) -> str:
    n = await db.vendor_shipments.count_documents({"parent_shipment_id": parent["id"], "shipment_type": stype})
    return f"{parent.get('shipment_number')}-{'A' if stype == 'ADDITIONAL' else 'R'}{n + 1}"


async def create_extra_shipment(db, *, payload: dict, stype: str, user: dict, notes: str = "",
                                extra: Optional[dict] = None, nota: Optional[dict] = None) -> dict:
    """Surat jalan tambahan/pengganti + item + SATU MI lewat `core.kirim_cmt`. Gagal → tidak meninggalkan apa pun.

    `nota` (11 Nov 2026, owner: nota untuk SETIAP penyerahan) = isian `nota_aksesoris` layar Setujui & kirim: harga
    jual aksesoris diperiksa SEBELUM apa pun ditulis, nota terbit sesudah stok keluar (`core.nota_aksesoris_cmt`)."""
    from core import kirim_cmt
    from core import material_issue_engine as mie
    from core import nota_aksesoris_cmt as nac
    from core.po_lock import assert_pos_open
    po = await db.production_pos.find_one({"id": payload["po_id"]}, {"_id": 0}) if payload.get("po_id") else None
    if not po:
        raise HTTPException(400, "Permintaan belum menunjuk PO yang ada — pilih PO dulu.")
    await assert_pos_open(db, {po["id"]}, "kiriman tambahan ke CMT")
    parent = await db.vendor_shipments.find_one({"id": payload.get("parent_id")}, {"_id": 0}) \
        if payload.get("parent_id") else None
    vendor_id = payload.get("vendor_id") or (parent or {}).get("vendor_id") or po.get("vendor_id")
    if not vendor_id:
        raise HTTPException(400, "Vendor CMT permintaan ini belum diketahui — PO belum punya vendor.")
    vendor = await db.vendor_partners.find_one({"id": vendor_id}, {"_id": 0}) or {}
    vname = (parent or {}).get("vendor_name") or vendor.get("name") or vendor.get("garment_name") or po.get("vendor_name") or ""
    if not payload["lines"] and not payload["materials"]:
        raise HTTPException(400, "Permintaan tidak berisi barang (pcs per SKU atau aksesoris) yang bisa dikirim.")
    nota_in = nac.parse_input(nota)
    if nota_in is not None and not (await nac.berlaku(db, vendor_id=vendor_id))["berlaku"]:
        nota_in = None                          # tim jahit CV sendiri: aksesoris tidak dijual
    if nota_in is not None:
        pre = await kirim_cmt.compute(db, po_id=po["id"], lines=payload["lines"], materials=payload["materials"],
                                      mode="tambahan", with_stock=False)
        kurang = nac.belum_berharga(pre.get("aksesoris") or [], nota_in["harga"])
        if kurang:
            raise HTTPException(400, "Isi harga jual aksesoris (isi 0 bila gratis): " + ", ".join(kurang[:6]) + ".")
    number = None
    if parent:
        number = await _child_number(db, parent, stype)
    else:
        from core.doc_number_policy import issue_number
        number = await issue_number(db, "vendor_shipments.shipment_number")
    sid = new_id()
    ship = {
        "id": sid, "shipment_number": number, "delivery_note_number": f"DN-{number}",
        "vendor_id": vendor_id, "vendor_name": vname, "po_id": po["id"], "po_number": po.get("po_number") or "",
        "shipment_date": now(), "shipment_type": stype, "parent_shipment_id": (parent or {}).get("id"),
        "business_type": po.get("business_type") or "internal", "status": "Sent",
        "notes": notes or (f"Kiriman tambahan dari {parent.get('shipment_number')}" if parent else "Kiriman tambahan"),
        "notes_for_vendor": notes, "created_by": user.get("name", ""), "created_at": now(), "updated_at": now(),
        **(extra or {}),
    }
    await db.vendor_shipments.insert_one(dict(ship))
    pis = {p["id"]: p async for p in db.po_items.find({"id": {"$in": [ln["po_item_id"] for ln in payload["lines"]]}},
                                                     {"_id": 0})} if payload["lines"] else {}
    items = []
    for ln in payload["lines"]:
        pi = pis.get(ln["po_item_id"]) or {}
        it = {"id": new_id(), "shipment_id": sid, "shipment_number": number, "po_id": po["id"],
              "po_number": po.get("po_number") or "", "po_item_id": ln["po_item_id"], "source_po_item_id": ln["po_item_id"],
              "product_name": pi.get("product_name") or ln.get("product_name") or "", "sku": pi.get("sku") or ln.get("sku") or "",
              "size": pi.get("size") or ln.get("size") or "", "color": pi.get("color") or ln.get("color") or "",
              "serial_number": ln.get("serial_number") or pi.get("serial_number") or "",
              "qty_sent": int(round(_f(ln["qty"]))), "ordered_qty": pi.get("qty") or 0, "shipment_type": stype,
              "parent_shipment_id": (parent or {}).get("id"), "created_at": now()}
        await db.vendor_shipment_items.insert_one(dict(it))
        items.append(it)

    async def _rollback():
        await db.vendor_shipment_items.delete_many({"shipment_id": sid})
        await db.accessory_shipment_items.delete_many({"shipment_id": sid})
        await db.vendor_shipments.delete_one({"id": sid})
        if not parent:
            from core.doc_number_policy import release_number
            await release_number(db, "vendor_shipments.shipment_number", number)
    try:
        res = await mie.issue_for_vendor_shipment(db, ship, items, user, mode="tambahan",
                                                  materials=payload["materials"])
    except kirim_cmt.KirimBlocked as e:
        await _rollback()
        raise HTTPException(400, "Kiriman tambahan TIDAK dibuat: " + "; ".join(e.reasons))
    except mie.MaterialShortage as e:
        await _rollback()
        raise HTTPException(400, f"Kiriman tambahan TIDAK dibuat: {e}")
    except mie.BomMissing as e:
        await _rollback()
        raise HTTPException(400, f"Kiriman tambahan TIDAK dibuat: {e}")
    except Exception:
        await _rollback()
        raise
    calc = res.get("kirim") or {}
    acc_sent = [{"accessory_id": a["material_id"], "accessory_code": a["code"], "accessory_name": a["name"],
                 "qty_sent": a["qty_handover"], "unit": a["handover_uom"], "unit_label": a["handover_label"],
                 "qty_base": a["qty_base"]} for a in calc.get("aksesoris") or [] if a.get("qty_handover")]
    if acc_sent:
        await db.vendor_shipments.update_one({"id": sid}, {"$set": {"accessory_count": len(acc_sent)}})
    ship = await db.vendor_shipments.find_one({"id": sid}, {"_id": 0})
    nota_out, nota_err = None, ""
    if nota_in is not None and not res.get("already"):
        try:
            nota_out = await nac.buat(db, shipment=ship, lines=nac.baris_dari_hitungan(calc.get("aksesoris") or [],
                                                                                       nota_in["harga"]),
                                      cara_bayar=nota_in["cara_bayar"], user=user)
        except HTTPException as e:
            nota_err = str(e.detail)
        except Exception:  # noqa: BLE001 — kiriman tetap sah (stok sudah keluar); nota dibuat dari rincian kiriman
            logger.exception("nota aksesoris kiriman tambahan %s gagal", number)
            nota_err = "Nota aksesoris gagal diterbitkan — buat dari rincian kiriman."
        ship = await db.vendor_shipments.find_one({"id": sid}, {"_id": 0})
    ship["accessory_items"] = acc_sent
    return {"shipment": ship, "items": items, "material_issue": res.get("mi"), "mi_number": res.get("mi_number"),
            "accessory_items": acc_sent, "nota_aksesoris": nac.ringkas(nota_out), "nota_aksesoris_error": nota_err}


async def approve_material_request(db, req: dict, body: dict, user: dict) -> dict:
    """`PUT /material-requests/{id}` status Approved → kiriman tambahan/pengganti yang MENGURANGI STOK."""
    from core.kirim_cmt import cancel_double_drafts
    if not await db.vendor_shipments.find_one({"id": req.get("original_shipment_id")}, {"_id": 1}):
        raise HTTPException(404, "Shipment asal tidak ditemukan")
    payload = await request_payload(db, SRC_VENDOR, req, body.get("accessory_items"))
    admin_notes = body.get("admin_notes", "") or ""
    out = await create_extra_shipment(db, payload=payload, stype=req["request_type"], user=user, notes=admin_notes,
                                      extra={"material_request_id": req["id"]}, nota=body.get("nota_aksesoris"))
    ship = out["shipment"]
    if out["accessory_items"] and req.get("inspection_id"):
        await db.dewi_cmt_component_requests.update_many(
            {"inspection_id": req["inspection_id"], "status": {"$in": ["pending", "approved"]}},
            {"$set": {"status": "delivered", "fulfilled_shipment_id": ship["id"],
                      "fulfilled_shipment_number": ship["shipment_number"], "delivered_at": now(), "updated_at": now()}})
    await db.material_requests.update_one({"id": req["id"]}, {"$set": {
        "status": "Approved", "admin_notes": admin_notes, "approved_by": user.get("name", ""), "approved_at": now(),
        "child_shipment_id": ship["id"], "child_shipment_number": ship["shipment_number"],
        "accessory_items_sent": out["accessory_items"],
        "material_issue_id": (out["material_issue"] or {}).get("id"), "material_issue_number": out["mi_number"],
        "updated_at": now()}})
    await cancel_double_drafts(db, payload["po_id"], actor=user.get("name", ""))
    from auth import serialize_doc
    result = serialize_doc(await db.material_requests.find_one({"id": req["id"]}, {"_id": 0}))
    result["child_shipment"] = serialize_doc(ship)
    result["nota_aksesoris"] = serialize_doc(out.get("nota_aksesoris"))
    result["nota_aksesoris_error"] = out.get("nota_aksesoris_error") or ""
    return result


async def approve_component_request(db, doc: dict, user: dict, body: Optional[dict] = None) -> dict:
    """Komponen Kurang / input staf disetujui → kiriman tambahan yang MENGURANGI STOK (dulu: MI tanpa surat jalan)."""
    body = body or {}
    if doc.get("status") == "delivered":
        raise HTTPException(400, "Permintaan ini sudah dikirim.")
    if doc.get("status") in ("rejected", "cancelled"):
        raise HTTPException(400, "Permintaan ini sudah ditolak/dibatalkan.")
    payload = await request_payload(db, SRC_STAF, doc)
    if any(not m.get("material_id") for m in payload["materials"]):
        raise HTTPException(400, "Permintaan ini punya baris tanpa barang dari Master Material — ubah permintaan dan "
                                 "pilih barangnya dulu sebelum disetujui.")
    out = await create_extra_shipment(db, payload=payload, stype="ADDITIONAL", user=user,
                                      notes=body.get("notes") or doc.get("notes") or "",
                                      extra={"component_request_id": doc["id"]}, nota=body.get("nota_aksesoris"))
    ship, mi = out["shipment"], out["material_issue"] or {}
    upd = {"status": "delivered", "delivered_by": user.get("name", ""), "delivered_at": now(),
           "fulfilled_shipment_id": ship["id"], "fulfilled_shipment_number": ship["shipment_number"],
           "delivery_order_number": ship["shipment_number"],
           "material_issue_id": mi.get("id"), "material_issue_number": out["mi_number"], "updated_at": now()}
    await db.dewi_cmt_component_requests.update_one({"id": doc["id"]}, {"$set": upd})
    if mi.get("id"):
        await db.rahaza_material_issues.update_one({"id": mi["id"]}, {"$set": {"component_request_id": doc["id"]}})
    return {"ok": True, "shipment_id": ship["id"], "shipment_number": ship["shipment_number"],
            "material_issue": {"material_issue_id": mi.get("id"), "material_issue_number": out["mi_number"],
                               "gl_je_number": (mi.get("_posting_result") or {}).get("je_number")},
            "nota_aksesoris": out.get("nota_aksesoris"), "nota_aksesoris_error": out.get("nota_aksesoris_error") or ""}


async def reject(db, src: str, doc: dict, reason: str, user: dict) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "Alasan penolakan wajib diisi (dibaca vendor/staf).")
    if src == SRC_VENDOR:
        if doc.get("status") != "Pending":
            raise HTTPException(400, f"Permintaan sudah '{doc.get('status')}' — keputusan hanya saat menunggu.")
        await db.material_requests.update_one({"id": doc["id"], "status": "Pending"}, {"$set": {
            "status": "Rejected", "admin_notes": reason, "rejected_by": user.get("name", ""), "rejected_at": now(),
            "updated_at": now()}})
    else:
        if doc.get("status") in ("delivered", "rejected", "cancelled"):
            raise HTTPException(400, "Permintaan ini sudah selesai.")
        await db.dewi_cmt_component_requests.update_one({"id": doc["id"]}, {"$set": {
            "status": "rejected", "rejection_reason": reason, "updated_at": now()}})


async def create_staff_request(db, body: dict, user: dict) -> dict:
    """Input staf (dulu "Komponen Kurang"): PO + pcs per SKU (potongan dari BOM) dan/atau aksesoris dalam satuan serah."""
    from core import satuan_serah as ss
    from core.po_lock import assert_po_open
    po = await db.production_pos.find_one({"id": body.get("po_id")}, {"_id": 0}) if body.get("po_id") else None
    if not po:
        raise HTTPException(400, "Pilih PO untuk permintaan ini.")
    await assert_po_open(db, po["id"], "permintaan tambahan ke CMT")
    lines_in = [x for x in body.get("lines") or [] if x.get("po_item_id") and _f(x.get("qty")) > 0]
    pis = {p["id"]: p async for p in db.po_items.find({"id": {"$in": [x["po_item_id"] for x in lines_in]},
                                                       "po_id": po["id"]}, {"_id": 0})} if lines_in else {}
    lines = []
    for x in lines_in:
        pi = pis.get(x["po_item_id"])
        if not pi:
            raise HTTPException(400, "Baris SKU bukan milik PO yang dipilih.")
        lines.append({"po_item_id": pi["id"], "sku": pi.get("sku") or "", "product_name": pi.get("product_name") or "",
                      "size": pi.get("size") or "", "color": pi.get("color") or "", "qty": int(round(_f(x["qty"])))})
    mats_in = [m for m in body.get("materials") or [] if m.get("material_id") and _f(m.get("qty")) > 0]
    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": [x["material_id"] for x in mats_in]}},
                                                              {"_id": 0})} if mats_in else {}
    items = []
    for x in mats_in:
        m = mats.get(x["material_id"])
        if not m or m.get("active") is False:
            raise HTTPException(400, f"Barang '{x['material_id']}' tidak ada / nonaktif di Master Material.")
        hu = ss.resolve_handover(m, x.get("uom"))
        items.append({"material_id": m["id"], "material_code": m.get("code") or "", "material_name": m.get("name") or "",
                      "component_type": m.get("name") or "", "qty": round(_f(x["qty"]), 4), "unit": hu["uom"],
                      "handover_uom": hu["uom"], "handover_factor": hu["factor"], "unit_label": hu["label"],
                      "notes": x.get("notes") or ""})
    if not lines and not items:
        raise HTTPException(400, "Isi minimal satu baris: pcs per SKU atau aksesoris.")
    shipment = await db.vendor_shipments.find_one({"id": body.get("source_shipment_id")}, {"_id": 0}) \
        if body.get("source_shipment_id") else None
    if shipment and shipment.get("po_id") and shipment["po_id"] != po["id"]:
        raise HTTPException(400, "Kiriman asal bukan milik PO yang dipilih.")
    vendor_id = (shipment or {}).get("vendor_id") or po.get("vendor_id") or body.get("vendor_id") or ""
    vendor = await db.vendor_partners.find_one({"id": vendor_id}, {"_id": 0}) if vendor_id else None
    if not vendor:
        raise HTTPException(400, "Vendor CMT belum diketahui — PO ini belum punya vendor.")
    vname = vendor.get("name") or vendor.get("garment_name") or ""
    from core.doc_number_policy import issue_number
    rtype = "component" if lines else "accessory"
    code = await issue_number(db, "dewi_cmt_component_requests.request_code",
                              ctx={"TIPE": "REQ-CMP" if rtype == "component" else "REQ-AKS-CMT"})
    doc = {
        "id": new_id(), "request_code": code, "request_type": rtype,
        "cmt_partner_id": vendor_id, "cmt_partner_name": vname, "vendor_id": vendor_id, "vendor_name": vname,
        "work_order_id": "", "work_order_code": po.get("po_number") or "", "model_id": "", "model_code": "",
        "product_name": (lines[0]["product_name"] if lines else (items[0]["material_name"] if items else "")),
        "po_id": po["id"], "po_number": po.get("po_number") or "", "inspection_id": "",
        "source_shipment_id": (shipment or {}).get("id") or "",
        "source_shipment_number": (shipment or {}).get("shipment_number") or "",
        "origin": "staf", "garment_lines": lines, "items": items,
        "fulfilled_shipment_id": None, "fulfilled_shipment_number": None,
        "material_issue_id": None, "material_issue_number": None,
        "urgent": bool(body.get("urgent")), "needed_by_date": body.get("needed_by_date") or "",
        "notes": (body.get("reason") or body.get("notes") or "").strip(), "status": "pending",
        "requester_id": user.get("id"), "requester_name": user.get("name", ""),
        "created_at": now(), "updated_at": now(),
    }
    await db.dewi_cmt_component_requests.insert_one(dict(doc))
    return doc
