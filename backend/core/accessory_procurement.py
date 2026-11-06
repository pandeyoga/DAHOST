"""core.accessory_procurement — pembelian aksesoris LEWAT PENGADAAN (2026-11-06, Tahap 2).

KENAPA ADA
  * "Buat Permintaan (N kurang)" di PO dulu membuat permintaan PENGELUARAN stok untuk barang yang
    justru KURANG stoknya — lalu saat diserahkan, stok yang ada (milik PO lain, bahkan aksesoris
    yang mestinya disediakan klien maklon) ikut terpotong. Kekurangan = barang yang harus DIBELI.
  * Request Pembelian Aksesoris (`acc_purchase_requests`) punya tombol "Terima Barang" yang menambah
    stok TANPA nilai dan TANPA jurnal, dan tidak pernah tersambung ke PO pengadaan.

Keduanya kini menjadi Permintaan Pengadaan (`dewi_procurement_requests`) lewat fungsi SSOT Portal
Pengadaan (`routes.dewi_procurement.build_pr_doc` + `submit_pr_doc`) — satuan, penomoran, rantai
persetujuan, PO, dan Penerimaan Barang (GR, bernilai & berjurnal) memakai jalur yang sudah ada.
"""
from __future__ import annotations

import logging

from core import accessory_issue as ai

log = logging.getLogger(__name__)

PR_COLL = "dewi_procurement_requests"
ORIGIN_PO_SHORTAGE = "po_accessory_shortage"
ORIGIN_ACC_PR = "accessory_pr"
PR_DEAD = ("rejected", "cancelled")
# Status Request Pembelian Aksesoris setelah diteruskan ke Permintaan Pengadaan
ACC_STATUS_FORWARDED = "Forwarded"
ACC_FORWARDABLE = ("Draft", "Submitted", "Approved", "Ordered")
_PRIORITY = {"urgent": "urgent", "normal": "medium", "low": "low", "high": "high"}

PR_STATUS_LABELS = {
    "draft": "Draf",
    "submitted": "Menunggu persetujuan departemen",
    "dept_approved": "Menunggu persetujuan keuangan",
    "finance_approved": "Menunggu persetujuan akhir",
    "approved": "Disetujui, menunggu PO",
    "in_procurement": "Sudah dibuat PO",
    "completed": "Selesai",
    "rejected": "Ditolak",
    "cancelled": "Dibatalkan",
}
PO_RECEIVE_LABELS = {
    "draft": "PO disusun",
    "pending_approval": "PO menunggu persetujuan",
    "approved": "Dipesan, menunggu barang",
    "partially_received": "Diterima sebagian",
    "fully_received": "Diterima lengkap",
    "rejected": "PO ditolak",
    "cancelled": "PO dibatalkan",
}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 1. KEBUTUHAN AKSESORIS PO — satu perhitungan untuk layar PO dan tombol "Ajukan Pembelian"
# ═════════════════════════════════════════════════════════════════════════════
async def po_requirements(db, po: dict) -> dict:
    """Baris `po_accessories` + posisi stok: dibutuhkan, sudah keluar untuk PO ini, sisa, tersedia,
    kurang (= yang perlu DIBELI). Baris maklon yang disediakan klien tidak dihitung kurang."""
    from core import stock_service

    po_id = po.get("id")
    rows = await db.po_accessories.find({"po_id": po_id}, {"_id": 0}).sort("created_at", 1).to_list(None)
    ids = [r.get("accessory_id") for r in rows if r.get("accessory_id")]
    onhand = await stock_service.onhand_map(ids, db=db) if ids else {}
    avail = await stock_service.available_map(ids, db=db) if ids else {}
    issued = await ai.po_issued_by_material(db, po_id)
    masters = {}
    if ids:
        async for m in db.rahaza_materials.find(
                {"id": {"$in": ids}},
                {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "unit_cost": 1, "hpp": 1}):
            masters[m["id"]] = m
    maklon = (po.get("business_type") or "") == "maklon"
    left_issued = dict(issued)       # dibagi berurutan bila satu material muncul di beberapa baris
    left_avail = {k: _f(v) for k, v in avail.items()}
    out, total_value = [], 0.0
    shortage_lines = unlinked_lines = client_lines = 0
    for r in rows:
        mid = r.get("accessory_id")
        master = masters.get(mid) or {}
        need = _f(r.get("qty_needed"))
        da_owned = (not maklon) or (r.get("ownership") or "") in ai.DA_OWNERSHIP
        unit_cost = _f(master.get("unit_cost") or master.get("hpp"))
        done = min(need, _f(left_issued.get(mid))) if mid else 0.0
        if mid:
            left_issued[mid] = _f(left_issued.get(mid)) - done
        remaining = round(max(need - done, 0.0), 3)
        have = 0.0
        if mid and da_owned:
            have = min(remaining, max(_f(left_avail.get(mid)), 0.0))
            left_avail[mid] = _f(left_avail.get(mid)) - have
        shortage = round(max(remaining - have, 0.0), 3) if (mid and da_owned) else 0.0
        if not mid:
            status = "unlinked"
            unlinked_lines += 1
        elif not da_owned:
            status = "client"
            client_lines += 1
        elif shortage > 0:
            status = "shortage"
            shortage_lines += 1
            total_value += shortage * unit_cost
        else:
            status = "ok"
        out.append({
            **r,
            "material_id": mid,
            "material_code": master.get("code") or r.get("accessory_code") or "",
            "material_name": master.get("name") or r.get("accessory_name") or "",
            "linked": bool(mid),
            "da_owned": da_owned,
            "on_hand": _f(onhand.get(mid)) if mid else 0.0,
            "available": round(_f(avail.get(mid)), 3) if mid else 0.0,
            "issued": round(done, 3),
            "remaining": remaining,
            "shortage": shortage,
            "unit_cost": unit_cost,
            "shortage_value": round(shortage * unit_cost, 2),
            "status": status,
        })
    return {
        "rows": out,
        "summary": {
            "total_lines": len(out),
            "shortage_lines": shortage_lines,
            "unlinked_lines": unlinked_lines,
            "client_lines": client_lines,
            "total_shortage_value": round(total_value, 2),
            "ready": shortage_lines == 0 and unlinked_lines == 0,
        },
    }


async def po_shortage_prs(db, po_id: str) -> list:
    """Permintaan Pengadaan kekurangan aksesoris yang pernah dibuat untuk PO ini (terbaru dulu)."""
    rows = await db[PR_COLL].find(
        {"origin": ORIGIN_PO_SHORTAGE, "production_po_id": po_id},
        {"_id": 0, "id": 1, "request_number": 1, "status": 1, "created_at": 1, "linked_po_number": 1},
    ).sort("created_at", -1).to_list(20)
    for r in rows:
        r["status_label"] = PR_STATUS_LABELS.get(r.get("status"), r.get("status") or "")
    return rows


async def create_po_shortage_pr(db, po: dict, user: dict, body: dict | None = None) -> dict:
    """Kekurangan aksesoris MILIK DA untuk PO → SATU Permintaan Pengadaan (langsung diajukan).

    Tidak memotong stok apa pun. Ditolak (`ValueError`) bila tidak ada yang kurang atau masih ada
    PR kekurangan aktif untuk PO ini (kecuali `force`)."""
    from routes.dewi_procurement import build_pr_doc, submit_pr_doc

    body = body or {}
    po_id = po["id"]
    if not body.get("force"):
        dup = await db[PR_COLL].find_one(
            {"origin": ORIGIN_PO_SHORTAGE, "production_po_id": po_id,
             "status": {"$nin": list(PR_DEAD) + ["completed"]}},
            {"_id": 0, "request_number": 1, "status": 1})
        if dup:
            raise ValueError(
                f"Permintaan Pengadaan kekurangan aksesoris untuk PO ini sudah ada: {dup.get('request_number')} "
                f"({PR_STATUS_LABELS.get(dup.get('status'), dup.get('status'))}). Selesaikan atau batalkan dulu.")
    req = await po_requirements(db, po)
    lines = [r for r in req["rows"] if r["status"] == "shortage"]
    if not lines:
        msg = "Tidak ada aksesoris milik DA yang kurang — tidak ada yang perlu dibeli."
        if req["summary"]["unlinked_lines"]:
            msg += (f" Catatan: {req['summary']['unlinked_lines']} baris belum tertaut ke master material "
                    "sehingga dilewati — perbaiki BOM-nya dulu.")
        raise ValueError(msg)
    po_no = po.get("po_number", "")
    items = [{
        "material_id": r["material_id"],
        "name": r["material_name"] or r["material_code"],
        "qty": r["shortage"],
        "estimated_price": r["unit_cost"],
        "notes": (f"Kekurangan PO {po_no}: butuh {r['qty_needed']:g}, sudah keluar {r['issued']:g}, "
                  f"stok tersedia {r['available']:g}"),
    } for r in lines]
    doc = await build_pr_doc(db, user, {
        "title": f"Kekurangan aksesoris PO {po_no}",
        "description": (body.get("notes") or "").strip()
                       or f"Dibuat otomatis dari kebutuhan aksesoris PO {po_no} (hanya aksesoris milik DA).",
        "justification": f"Stok aksesoris tidak cukup untuk PO {po_no}.",
        "request_type": "consumable",
        "priority": "urgent" if body.get("urgent") else "medium",
        "needed_by": body.get("needed_by") or None,
        "items": items,
    }, origin=ORIGIN_PO_SHORTAGE)
    doc.update({"production_po_id": po_id, "production_po_number": po_no,
                "production_po_business_type": po.get("business_type") or ""})
    await db[PR_COLL].insert_one(dict(doc))
    await submit_pr_doc(db, doc, user)
    return {"request": doc, "lines": len(items),
            "lines_skipped_unlinked": req["summary"]["unlinked_lines"],
            "lines_skipped_client": req["summary"]["client_lines"]}


# ═════════════════════════════════════════════════════════════════════════════
# 2. REQUEST PEMBELIAN AKSESORIS → PERMINTAAN PENGADAAN
# ═════════════════════════════════════════════════════════════════════════════
def acc_pr_body(acc: dict, mats: dict | None = None) -> dict:
    """Fungsi murni: Request Pembelian Aksesoris → body `build_pr_doc` (qty & harga per satuan dasar)."""
    mats = mats or {}
    items = []
    for it in acc.get("items") or []:
        mid = it.get("acc_id") or it.get("material_id") or None
        qty = _f(it.get("qty_requested") or it.get("qty"))
        if qty <= 0:
            continue
        m = mats.get(mid) or {}
        items.append({
            "material_id": mid,
            "name": it.get("acc_name") or it.get("material_name") or m.get("name") or it.get("acc_code") or "",
            "qty": qty,
            "estimated_price": _f(it.get("estimated_price")),
            "notes": it.get("notes", ""),
        })
    supplier = (acc.get("supplier") or "").strip()
    desc = (acc.get("notes") or "").strip()
    if supplier:
        desc = (desc + "\n" if desc else "") + f"Pemasok usulan: {supplier}"
    return {
        "title": (acc.get("purpose") or "").strip() or f"Pembelian aksesoris {acc.get('pr_number', '')}",
        "description": desc,
        "justification": (acc.get("purpose") or "").strip(),
        "request_type": "consumable",
        "priority": _PRIORITY.get((acc.get("priority") or "Normal").strip().lower(), "medium"),
        "department": acc.get("department") or "",
        # 2026-11-07 (Tahap 6 PG5): supplier usulan yang tertaut master ikut sebagai saran supplier PR
        "suggested_supplier_id": acc.get("supplier_id") or None,
        "items": items,
    }


def _carry_state(acc: dict) -> dict:
    """Status Permintaan Pengadaan untuk PR aksesoris LAMA yang sudah berjalan (migrasi)."""
    from core.pr_approval import STAGE_TO_STATUS, STAGE_DEPT
    st = acc.get("status")
    carry = {"approval_steps": list(acc.get("approval_steps") or []),
             "approval_chain": list(acc.get("approval_chain") or []),
             "approval_thresholds": acc.get("approval_thresholds") or {}}
    if st == "Submitted":
        stage = acc.get("current_approver_stage") or STAGE_DEPT
        carry.update(status=STAGE_TO_STATUS.get(stage, "submitted"), current_approver_stage=stage,
                     current_approver_role=stage, submitted_at=acc.get("submitted_at") or None)
    elif st in ("Approved", "Ordered"):
        carry.update(status="approved", current_approver_stage=None, current_approver_role=None,
                     submitted_at=acc.get("submitted_at") or None,
                     approved_at=acc.get("approved_at") or None)
    return carry


async def forward_acc_pr(db, acc: dict, user: dict, *, submit: bool) -> dict:
    """Teruskan SATU Request Pembelian Aksesoris ke Permintaan Pengadaan (idempoten).

    submit=True  → jalur normal tombol "Ajukan": PR pengadaan dibuat lalu langsung diajukan.
    submit=False → migrasi: status PR aksesoris lama dibawa (draf tetap draf; diajukan / disetujui
                   membawa rantai & jejak persetujuannya)."""
    from core.pr_approval import acc_material_map
    from routes.dewi_procurement import build_pr_doc, submit_pr_doc

    if acc.get("procurement_pr_id"):
        pr = await db[PR_COLL].find_one({"id": acc["procurement_pr_id"]}, {"_id": 0})
        if pr and submit and pr.get("status") == "draft":
            await submit_pr_doc(db, pr, user)
            pr = await db[PR_COLL].find_one({"id": pr["id"]}, {"_id": 0})
        return {"already": True, "request": pr}
    mats = await acc_material_map(db, [acc])
    body = acc_pr_body(acc, mats)
    if not body["items"]:
        raise ValueError("Request pembelian aksesoris ini tidak punya baris barang yang bisa dibeli.")
    owner = {"id": acc.get("requested_by") or user.get("id"),
             "name": acc.get("requested_by_name") or user.get("name", ""),
             "department": acc.get("department") or ""}
    doc = await build_pr_doc(db, owner, body, origin=ORIGIN_ACC_PR)
    doc.update({"acc_pr_id": acc["id"], "acc_pr_number": acc.get("pr_number", "")})
    if not submit and acc.get("status") != "Draft":
        doc.update(_carry_state(acc))
    await db[PR_COLL].insert_one(dict(doc))
    if submit:
        await submit_pr_doc(db, doc, user)
    step = {"id": doc["id"] + ":fwd", "step": "forward", "stage": None,
            "actor_id": user.get("id"), "actor_name": user.get("name", "") or user.get("email", ""),
            "actor_role": (user.get("role") or "").lower(), "action": "forwarded",
            "action_label": f"Diteruskan ke Permintaan Pengadaan {doc['request_number']}",
            "comment": "", "timestamp": doc["created_at"].isoformat()
            if hasattr(doc.get("created_at"), "isoformat") else str(doc.get("created_at"))}
    await db.acc_purchase_requests.update_one({"id": acc["id"]}, {
        "$set": {"status": ACC_STATUS_FORWARDED, "status_before_forward": acc.get("status"),
                 "procurement_pr_id": doc["id"], "procurement_pr_number": doc["request_number"],
                 "current_approver_stage": None, "updated_at": step["timestamp"]},
        "$push": {"approval_steps": step}})
    fresh = await db[PR_COLL].find_one({"id": doc["id"]}, {"_id": 0})
    return {"already": False, "request": fresh}


async def link_info(db, docs: list) -> dict:
    """{acc_pr_id: info} status Permintaan Pengadaan + PO + penerimaan untuk PR aksesoris yang diteruskan."""
    pr_ids = [d.get("procurement_pr_id") for d in docs if d.get("procurement_pr_id")]
    if not pr_ids:
        return {}
    prs = {p["id"]: p async for p in db[PR_COLL].find(
        {"id": {"$in": pr_ids}},
        {"_id": 0, "id": 1, "request_number": 1, "status": 1, "linked_po_id": 1, "linked_po_number": 1})}
    po_ids = [p.get("linked_po_id") for p in prs.values() if p.get("linked_po_id")]
    pos = {}
    if po_ids:
        async for po in db.rahaza_purchase_orders.find({"id": {"$in": po_ids}},
                                                       {"_id": 0, "id": 1, "po_number": 1, "status": 1}):
            pos[po["id"]] = po
    out = {}
    for d in docs:
        p = prs.get(d.get("procurement_pr_id"))
        if not p:
            continue
        po = pos.get(p.get("linked_po_id")) or {}
        out[d["id"]] = {
            "pr_id": p["id"], "pr_number": p.get("request_number", ""),
            "pr_status": p.get("status", ""),
            "pr_status_label": PR_STATUS_LABELS.get(p.get("status"), p.get("status") or ""),
            "po_number": po.get("po_number") or p.get("linked_po_number") or "",
            "po_status": po.get("status", ""),
            "receive_label": PO_RECEIVE_LABELS.get(po.get("status"), "") if po else "",
        }
    return out
