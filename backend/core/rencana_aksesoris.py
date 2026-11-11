"""core.rencana_aksesoris — simpan RENCANA AKSESORIS PO (Tahap 9, keputusan owner no. 3).

Satu penulis untuk isian user di bagian "Aksesoris" form PO (dipakai `PUT /production-pos/{id}` delta,
`POST /po-accessories`, dan `PUT /kirim-cmt/po/{id}/accessory-plan`):

  * baris dari BOM (`source='bom'`) — perkiraan BOM & satuan dasar TETAP milik mesin BOM; user hanya mengubah
    rencana serah (`plan_qty_handover`) dan boleh memilih satuan serah lain dari daftar satuan material;
  * baris tambahan di luar BOM (`source='tambahan'`) — satuan mengikuti material (bukan selalu "pcs"), qty diisi
    dalam satuan serah; `qty_needed` (satuan dasar) diturunkan dari rencana × isi kemasan.
Baris BOM tidak pernah dihapus dari sini (dihitung ulang oleh mesin BOM saat qty/artikel PO berubah)."""
from __future__ import annotations

from core import satuan_serah as ss
from core.helpers import new_id, now


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def apply_rows(db, po_id: str, rows: list, *, replace_tambahan: bool = True) -> dict:
    """Terapkan baris form ke `po_accessories` PO ini. Return {bom_updated, tambahan_saved, tambahan_deleted}."""
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "id": 1, "business_type": 1}) or {}
    maklon = (po.get("business_type") or "") == "maklon"
    existing = await db.po_accessories.find({"po_id": po_id}, {"_id": 0}).to_list(2000)
    by_id = {r["id"]: r for r in existing if r.get("id")}
    auto_by_key = {ss.row_key(r): r for r in existing if ss.is_auto_row(r)}
    mat_ids = [r.get("accessory_id") for r in rows or [] if r.get("accessory_id")] + \
              [r.get("accessory_id") for r in existing if r.get("accessory_id")]
    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": sorted(set(mat_ids))}}, {"_id": 0})} \
        if mat_ids else {}
    keep, out = set(), {"bom_updated": 0, "tambahan_saved": 0, "tambahan_deleted": 0}
    for raw in rows or []:
        if not (raw.get("accessory_name") or raw.get("accessory_id")):
            continue
        target = by_id.get(raw.get("id"))
        if (target and ss.is_auto_row(target)) or (raw.get("source") == ss.SOURCE_BOM and not target):
            t = target or auto_by_key.get(ss.row_key(raw))
            if not t:
                continue
            keep.add(t["id"])
            if raw.get("plan_qty_handover") in (None, "") and not raw.get("handover_uom") and "harga_jual_cmt" not in raw:
                continue
            mat = mats.get(t.get("accessory_id"))
            est = t.get("bom_qty_base") if t.get("bom_qty_base") not in (None, "") else t.get("qty_needed")
            plan = raw.get("plan_qty_handover")
            if plan in (None, ""):
                plan = t.get("plan_qty_handover")
            pf = ss.plan_fields(mat, bom_qty_base=est, source=ss.SOURCE_BOM, plan_qty_handover=plan,
                                handover_uom=raw.get("handover_uom") or t.get("handover_uom"),
                                usage_unit=t.get("unit") or "")
            pf["plan_edited"] = abs(_f(pf["plan_qty_handover"]) - _f(pf["bom_qty_handover"])) > 1e-9
            if "harga_jual_cmt" in raw:     # owner 11 Nov 2026: harga jual ke CMT diisi di PO (per satuan serah)
                pf.update(ss.harga_fields(mat, raw.get("harga_jual_cmt"), pf.get("handover_uom")))
            await db.po_accessories.update_one({"id": t["id"]}, {"$set": {**pf, "updated_at": now()}})
            out["bom_updated"] += 1
            continue
        mat = mats.get(raw.get("accessory_id"))
        hu = ss.resolve_handover(mat, raw.get("handover_uom"))
        plan = raw.get("plan_qty_handover")
        if plan in (None, ""):          # klien lama: qty_needed dalam satuan dasar
            plan = round(_f(raw.get("qty_needed")) / (hu["factor"] or 1.0), 4)
        pf = ss.plan_fields(mat, source=ss.SOURCE_TAMBAHAN, plan_qty_handover=plan, handover_uom=hu["uom"],
                            usage_unit=raw.get("unit") or "")
        doc = {"po_id": po_id, "accessory_id": raw.get("accessory_id"),
               "accessory_name": (mat or {}).get("name") or raw.get("accessory_name") or "",
               "accessory_code": (mat or {}).get("code") or raw.get("accessory_code") or "",
               "notes": raw.get("notes") or "", "unlinked": mat is None, **pf}
        if "harga_jual_cmt" in raw:
            doc.update(ss.harga_fields(mat, raw.get("harga_jual_cmt"), pf.get("handover_uom")))
        if maklon:
            doc["ownership"] = raw.get("ownership") or "cv_da_stock"   # tambahan di PO maklon = disediakan DA
        if target and not ss.is_auto_row(target):
            await db.po_accessories.update_one({"id": target["id"]}, {"$set": {**doc, "updated_at": now()}})
            keep.add(target["id"])
        else:
            nid = new_id()
            await db.po_accessories.insert_one({**doc, "id": nid, "created_at": now()})
            keep.add(nid)
        out["tambahan_saved"] += 1
    if replace_tambahan:
        for r in existing:
            if r.get("id") and r["id"] not in keep and not ss.is_auto_row(r):
                await db.po_accessories.delete_one({"id": r["id"]})
                out["tambahan_deleted"] += 1
    return out
