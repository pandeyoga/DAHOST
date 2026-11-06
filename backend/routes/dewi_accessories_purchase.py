"""
Dewi Accessories - Purchase
Purchase requests to finance
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import uuid
import logging
from datetime import datetime, timezone
from database import get_db
from auth import require_auth, serialize_doc

_log = logging.getLogger(__name__)

router = APIRouter(tags=["accessories-purchase"])

# ── helpers ──────────────────────────────────────────────────────────────────
def _id():    return str(uuid.uuid4())
def _now_iso(): return datetime.now(timezone.utc).isoformat()
def _now():   return datetime.now(timezone.utc)

# 2026-11-06 (pola P8): salinan `_normalize_unit`/`_VALID_UNITS` yang tidak dipakai dihapus —
# ejaan satuan resmi ada di `core.uom.canonical_unit` (dipakai `dewi_accessories_items`).

# Fase 2.8: helper stok aksesoris KANONIK dipindah ke core.accessory_stock
# (satukan ke rahaza_material_stock flat via stock_service; hilangkan duplikasi Schema-B nested).
from core.accessory_stock import (  # noqa: E402
    get_accessory_location_id as _get_accessory_location_id,
)

async def _log_movement(db, user: dict, *, material_id: str, mv_type: str, qty: float,
                        notes: str = "", related_ref: str = "", related_type: str = ""):
    mat = await db.rahaza_materials.find_one(
        {"id": material_id}, {"_id": 0, "id": 1, "code": 1, "name": 1, "type": 1, "unit": 1}
    )
    if not mat:
        return
    loc_id = await _get_accessory_location_id(db)
    mvdoc = {
        "id": _id(),
        "material_id": material_id,
        "material": mat,
        "movement_type": mv_type,
        "qty_signed": qty,
        "location": {"id": loc_id, "code": "ZNA-AKSESORIS", "name": "Area Aksesoris"},
        "notes": notes,
        "reference_type": related_type,
        "reference_id": related_ref,
        "created_by": user.get("id", ""),
        "created_at": _now(),
    }
    await db.rahaza_material_movements.insert_one(mvdoc)

# 2026-11-06 (pola P2): salinan `_enrich_movement` yang tidak pernah dipanggil dihapus — versi yang
# dipakai ada di routes/dewi_accessories_stock.py (dulu salinan ini membaca `dewi_asset_loans` lewat
# `related_loan_id` yang tidak pernah ditulis).

# (dead code dibersihkan) _material_to_acc_item duplikat tak terpakai — SSOT serializer item aksesoris ada di routes/dewi_accessories_items.py

@router.get("/purchase-requests")
async def list_purchase_requests(request: Request):
    user = await require_auth(request)
    db = get_db()
    sp = request.query_params
    query: dict = {}
    if sp.get("status"):
        query["status"] = sp["status"]
    docs = await db.acc_purchase_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Flag izin dari SERVER (SSOT). Frontend DILARANG menebak dari status/peran:
    # sampai 2026-08-07 tabel ini merender tombol "Setujui" untuk SIAPA PUN yang
    # login, dan backend-nya memang menerimanya (tanpa RBAC sama sekali).
    from core.pr_approval import (
        STAGE_DEPT, chain_config, doc_chain, eval_approval, with_department,
    )
    cfg = await chain_config(db)
    u = await with_department(db, user)
    # 2026-11-06 (Tahap 2): PR yang sudah diteruskan menampilkan status Permintaan Pengadaan, PO &
    # penerimaannya (barang masuk lewat Penerimaan Barang — bernilai & berjurnal).
    from core.accessory_procurement import link_info
    links = await link_info(db, docs)
    out = []
    for d in docs:
        chain = doc_chain(d, cfg)
        stage = d.get("current_approver_stage") if d.get("status") == "Submitted" else None
        if d.get("status") == "Submitted" and not stage:
            stage = STAGE_DEPT
        row = serialize_doc(d)
        row.update(eval_approval(d, u, chain, stage=stage))
        link = links.get(d.get("id"))
        row["procurement"] = link
        is_owner = (not d.get("requested_by") or d.get("requested_by") == user.get("id")
                    or (user.get("role") or "").lower() in ("superadmin", "admin", "owner"))
        # Draf (atau sudah diteruskan tapi PR pengadaannya masih draf hasil migrasi) → boleh diajukan
        row["can_submit"] = is_owner and (
            d.get("status") == "Draft"
            or (d.get("status") == "Forwarded" and (link or {}).get("pr_status") == "draft"))
        if d.get("status") == "Forwarded":
            row.update(can_approve=False, can_reject=False)
        out.append(row)
    return out


@router.post("/purchase-requests")
async def create_purchase_request(request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "items wajib diisi")
    
    # Konversi kemasan → satuan dasar untuk setiap baris.
    # INV-UOM-1 & INV-UOM-2: qty dan harga yang DISIMPAN selalu dalam satuan dasar.
    # BUG-8 (2026-07-27): sebelumnya hanya qty yang dikonversi, sedangkan
    # `estimated_price` (harga per kemasan yang diketik user) tetap dikalikan qty
    # satuan dasar → total estimasi membengkak sebesar `pack_size`.
    for item in items:
        input_unit = (item.get("input_unit") or "base").strip().lower()
        if input_unit == "pack" and item.get("acc_id"):
            mat = await db.rahaza_materials.find_one({"id": item["acc_id"]}, {"_id": 0})
            if mat and mat.get("pack_size"):
                pack_size = float(mat.get("pack_size") or 1) or 1
                if pack_size <= 0:
                    pack_size = 1
                qty_in_packs = float(item.get("qty_requested") or 0)
                qty_in_base = qty_in_packs * pack_size
                item["qty_requested"] = qty_in_base
                item["qty_requested_in_packs"] = qty_in_packs
                item["pack_unit"] = mat.get("pack_unit", "pack")
                item["pack_size"] = pack_size

                # Harga: default mengikuti satuan input (user mengetik harga per kemasan).
                # `cost_unit` boleh dikirim eksplisit untuk menimpa perilaku default.
                cost_unit = (item.get("cost_unit") or input_unit).strip().lower()
                price_raw = float(item.get("estimated_price") or 0)
                if cost_unit == "pack" and price_raw > 0:
                    item["estimated_price_per_pack"] = price_raw
                    item["estimated_price"] = price_raw / pack_size
                item["cost_unit"] = "base"  # setelah konversi, selalu per satuan dasar
                _log.info(
                    f"PR pack mode: {qty_in_packs} {item['pack_unit']} × {pack_size} = {qty_in_base} "
                    f"| harga {price_raw}/{cost_unit} → {item.get('estimated_price')}/satuan dasar"
                )

    # SESI #27 — SATU PINTU kebijakan penomoran (Otomatis/Manual).
    from core.doc_number_policy import issue_number
    pr_number = await issue_number(db, "acc_purchase_requests.pr_number",
                                   requested=(body.get("pr_number") or "").strip())
    doc = {
        "id": _id(),
        "pr_number": pr_number,
        "priority": body.get("priority", "Normal"),
        "purpose": body.get("purpose", ""),
        "supplier": body.get("supplier", ""),
        "items": items,
        "total_estimated": sum(
            float(i.get("qty_requested") or 0) * float(i.get("estimated_price") or 0)
            for i in items
        ),
        "notes": body.get("notes", ""),
        "status": "Draft",
        "submitted_at": "",
        "approved_by": "", "approved_at": "",
        "finance_notes": "",
        # 2026-08-07 — WAJIB untuk pemisahan wewenang: dulu hanya `created_by`
        # (STRING nama) yang disimpan, sehingga tidak mungkin tahu SIAPA pembuatnya
        # dan aturan "pembuat tidak boleh menyetujui sendiri" tidak bisa ditegakkan.
        "requested_by": user.get("id"),
        "requested_by_name": user.get("name", "") or user.get("email", ""),
        "department": (body.get("department") or user.get("department") or "").strip(),
        "approval_steps": [],
        "approval_chain": [],
        "current_approver_stage": None,
        "created_by": user.get("name", ""),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.acc_purchase_requests.insert_one(doc)
    return JSONResponse(serialize_doc(doc), status_code=201)


@router.put("/purchase-requests/{pr_id}")
async def update_purchase_request(pr_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    doc = await db.acc_purchase_requests.find_one({"id": pr_id})
    if not doc:
        raise HTTPException(404, "PR tidak ditemukan")

    new_status = body.get("status")
    upd: dict = {"updated_at": _now_iso()}

    # ── GERBANG 2026-08-07 ───────────────────────────────────────────────────
    # LUBANG YANG DITUTUP: endpoint ini hanya memakai `require_auth`, sehingga
    # SIAPA PUN yang login bisa mengubah status apa saja — terbukti akun
    # `tim_packing` membuat PR aksesoris Rp 50 juta lalu MENYETUJUI SENDIRI
    # (HTTP 200). Sekarang keputusan persetujuan HANYA lewat
    # /submit · /approve · /reject yang memakai mesin `core/pr_approval.py`
    # (sama dengan Permintaan Pengadaan), dan Ordered/Received butuh peran
    # pengadaan/gudang karena "Received" MENAMBAH STOK.
    if new_status in ("Submitted", "Approved", "Rejected"):
        raise HTTPException(400,
            "Perubahan status persetujuan tidak lagi lewat endpoint ini. "
            "Gunakan /purchase-requests/{id}/submit, /approve, atau /reject "
            "supaya aturan persetujuan & jejak auditnya tercatat.")
    if new_status in ("Ordered", "Received", "Forwarded"):
        # 2026-11-06 (Tahap 2): "Diterima" dulu MENAMBAH STOK tanpa nilai & tanpa jurnal (stok ≠ buku
        # besar) dan tidak pernah tersambung ke PO pengadaan. Pesan & terima sekarang HANYA lewat
        # Pengadaan: Permintaan Pengadaan → PO → Penerimaan Barang (bernilai, berjurnal).
        raise HTTPException(400,
            "Pemesanan dan penerimaan aksesoris kini lewat Pengadaan: ajukan PR ini (otomatis diteruskan "
            "ke Permintaan Pengadaan), lalu buat PO dan terima barangnya di Penerimaan Barang supaya stok "
            "masuk dengan nilai dan jurnal.")
    if doc.get("status") == "Forwarded":
        raise HTTPException(400, "PR ini sudah diteruskan ke Permintaan Pengadaan "
                                 f"{doc.get('procurement_pr_number', '')} — ubah di sana.")
    if new_status and new_status != doc.get("status") and not (
            new_status == "Cancelled" and doc.get("status") in ("Draft", "Rejected")):
        raise HTTPException(400, "Status PR hanya bisa diubah lewat tombol Ajukan / Setujui / Tolak.")
    # field alur kerja / tautan tidak boleh ditimpa lewat ubah detail
    locked = ("_id", "id", "created_at", "created_by", "pr_number", "requested_by",
              "approval_steps", "approval_chain", "current_approver_stage", "procurement_pr_id",
              "procurement_pr_number", "status_before_forward")
    upd.update({k: v for k, v in body.items() if k not in locked})

    await db.acc_purchase_requests.update_one({"id": pr_id}, {"$set": upd})
    result = await db.acc_purchase_requests.find_one({"id": pr_id}, {"_id": 0})
    return serialize_doc(result)


# ═══════════════════════════════════════════════════════════════════════════
# PERSETUJUAN — memakai mesin YANG SAMA dengan Permintaan Pengadaan
# (core/pr_approval.py). Menjawab laporan owner 2026-08-07: "purchase request
# di aksesoris & gudang harusnya tersambung ke procurement."
#
# Efeknya: rantai tahap mengikuti NILAI PR + ambang yang diatur owner, dibekukan
# saat submit; peran per tahap saling lepas; pembuat tidak boleh menyetujui PR-nya
# sendiri; satu orang tidak boleh menyetujui dua tahap; admin boleh override tapi
# TERCATAT; approver berikutnya dapat notifikasi; dan PR ini tampil di kotak
# persetujuan gabungan `/api/procurement/inbox` + lencana TopBar.
# ═══════════════════════════════════════════════════════════════════════════

def _acc_out(doc: dict, ev: dict, mats: dict | None = None) -> dict:
    from core.pr_approval import normalize_acc_pr
    out = serialize_doc(normalize_acc_pr(doc, mats))
    out.update(ev)
    return out


async def _acc_ctx(db, pr_id: str, user: dict):
    """Ambil PR aksesoris + hak persetujuan user atasnya."""
    from core.pr_approval import (
        STAGE_DEPT, chain_config, doc_chain, eval_approval, with_department,
    )
    doc = await db.acc_purchase_requests.find_one({"id": pr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "PR tidak ditemukan")
    cfg = await chain_config(db)
    chain = doc_chain(doc, cfg)
    stage = doc.get("current_approver_stage") if doc.get("status") == "Submitted" else None
    if doc.get("status") == "Submitted" and not stage:
        stage = STAGE_DEPT
    u = await with_department(db, user)
    return doc, chain, eval_approval(doc, u, chain, stage=stage), cfg


@router.get("/purchase-requests/{pr_id}")
async def get_purchase_request(pr_id: str, request: Request):
    """Detail PR aksesoris dalam BENTUK yang sama dengan Permintaan Pengadaan,
    lengkap dengan flag izin dari server (frontend dilarang menebak sendiri)."""
    user = await require_auth(request)
    db = get_db()
    doc, _chain, ev, _cfg = await _acc_ctx(db, pr_id, user)
    from core.pr_approval import acc_material_map
    return _acc_out(doc, ev, await acc_material_map(db, [doc]))


@router.get("/purchase-requests/{pr_id}/timeline")
async def get_purchase_request_timeline(pr_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc, _chain, ev, _cfg = await _acc_ctx(db, pr_id, user)
    return {"steps": doc.get("approval_steps", []),
            "current_status": doc.get("status"),
            "chain": ev["chain"], "approval_chain": ev["approval_chain"],
            "total_stages": ev["total_stages"], "stage": ev["stage"],
            "stage_label": ev["stage_label"],
            "next_approver_label": ev["next_approver_label"]}


@router.post("/purchase-requests/{pr_id}/submit")
async def submit_purchase_request(pr_id: str, request: Request):
    from core.pr_approval import SUPER_APPROVER_ROLES
    user = await require_auth(request)
    db = get_db()
    doc = await db.acc_purchase_requests.find_one({"id": pr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "PR tidak ditemukan")
    from core import accessory_procurement as ap
    if doc.get("status") not in ("Draft", ap.ACC_STATUS_FORWARDED):
        raise HTTPException(400, "Hanya PR berstatus Draft yang bisa diajukan.")
    owner_id = doc.get("requested_by")
    if owner_id and owner_id != user.get("id") \
            and (user.get("role") or "").lower() not in SUPER_APPROVER_ROLES:
        raise HTTPException(403, "Hanya pembuat PR atau admin yang boleh mengajukan.")

    # 2026-11-06 (Tahap 2): MENGAJUKAN = meneruskan ke Permintaan Pengadaan (dibuat + langsung diajukan
    # lewat fungsi Portal Pengadaan). Persetujuan, PO, dan Penerimaan Barang (bernilai & berjurnal)
    # berjalan di sana — tidak ada lagi jalur persetujuan & "Terima Barang" kedua di PR aksesoris.
    try:
        res = await ap.forward_acc_pr(db, doc, user, submit=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    pr = res.get("request") or {}
    return {"ok": True, "new_status": ap.ACC_STATUS_FORWARDED,
            "procurement_pr_id": pr.get("id"), "procurement_pr_number": pr.get("request_number", ""),
            "procurement_status": pr.get("status", ""),
            "message": (f"Diteruskan ke Permintaan Pengadaan {pr.get('request_number', '')} dan diajukan ke "
                        "persetujuan. Barang masuk stok lewat PO dan Penerimaan Barang.")}


@router.post("/purchase-requests/{pr_id}/forward")
async def forward_purchase_request(pr_id: str, request: Request):
    """2026-11-06 (Tahap 2): teruskan PR aksesoris LAMA yang sudah diajukan / disetujui / dipesan
    (sebelum alur Pengadaan) ke Permintaan Pengadaan, membawa status & jejak persetujuannya, supaya
    barangnya bisa dibuatkan PO dan diterima lewat Penerimaan Barang. Sama dengan skrip migrasi."""
    from routes.shared import assert_can_act
    from core import accessory_procurement as ap
    user = await require_auth(request)
    assert_can_act(user, "purchasing.manage", "proc.po.manage",
                   legacy_roles=("admin_pengadaan", "manager_pengadaan", "purchasing",
                                 "admin_aksesoris", "spv_aksesoris"),
                   what="meneruskan PR aksesoris ke Pengadaan")
    db = get_db()
    doc = await db.acc_purchase_requests.find_one({"id": pr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "PR tidak ditemukan")
    if doc.get("status") not in ap.ACC_FORWARDABLE and doc.get("status") != ap.ACC_STATUS_FORWARDED:
        raise HTTPException(400, f"PR berstatus {doc.get('status')} tidak perlu diteruskan.")
    try:
        res = await ap.forward_acc_pr(db, doc, user, submit=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    pr = res.get("request") or {}
    return {"ok": True, "already": res.get("already", False),
            "procurement_pr_number": pr.get("request_number", ""), "procurement_status": pr.get("status", "")}


@router.post("/purchase-requests/{pr_id}/approve")
async def approve_purchase_request(pr_id: str, request: Request):
    from core.pr_approval import (
        STAGE_LABELS, next_stage_after, notify_requester, notify_stage_approvers,
    )
    user = await require_auth(request)
    db = get_db()
    doc, chain, ev, _cfg = await _acc_ctx(db, pr_id, user)
    if doc.get("status") != "Submitted":
        raise HTTPException(400, f"Status '{doc.get('status')}' tidak bisa disetujui.")
    if not ev["can_approve"]:
        raise HTTPException(403, ev["blocked_reason"]
                            or "Akses ditolak: Anda tidak berhak menyetujui permintaan ini.")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    comment = (body.get("comment") or body.get("finance_notes") or "").strip()

    stage = ev["stage"]
    nxt = next_stage_after(chain, stage)
    label = f"Disetujui — {STAGE_LABELS.get(stage, stage)}"
    if ev["is_override"]:
        label += " (override admin)"
    step = {
        "id": _id(), "step": stage, "stage": stage,
        "actor_id": user.get("id"),
        "actor_name": user.get("name", "") or user.get("email", ""),
        "actor_role": (user.get("role") or "").lower(),
        "action": "approved", "action_label": label, "comment": comment,
        "override": bool(ev["is_override"]),
        "override_reasons": list(ev["override_reasons"]),
        "timestamp": _now_iso(),
    }
    upd = {"current_approver_stage": nxt, "approval_chain": chain,
           "updated_at": _now_iso(), "finance_notes": comment or doc.get("finance_notes", "")}
    if not nxt:
        upd.update({"status": "Approved",
                    "approved_by": step["actor_name"], "approved_at": _now_iso()})
    await db.acc_purchase_requests.update_one({"id": pr_id},
                                              {"$set": upd, "$push": {"approval_steps": step}})
    after = {**doc, **upd}
    if nxt:
        await notify_stage_approvers(db, after, nxt, chain,
                                     module_id="proc-accessory-pr",
                                     number=doc.get("pr_number", ""),
                                     title=doc.get("purpose", ""),
                                     kind_label="Request Pembelian Aksesoris")
    else:
        await notify_requester(
            db, after, severity="success", module_id="proc-accessory-pr",
            number=doc.get("pr_number", ""),
            title="Request Pembelian Aksesoris Anda disetujui penuh",
            body=(f"{doc.get('pr_number', '')} — {doc.get('purpose', '')}\n"
                  "Semua tahap persetujuan selesai. Langkah berikutnya: pesan ke supplier."))
    return {"ok": True, "new_status": upd.get("status", "Submitted"),
            "stage_approved": stage, "stage_label": STAGE_LABELS.get(stage, ""),
            "next_stage": nxt,
            "next_stage_label": STAGE_LABELS.get(nxt, "") if nxt else "",
            "override": bool(ev["is_override"]),
            "override_reasons": list(ev["override_reasons"]),
            "approval_chain": chain, "total_stages": len(chain)}


@router.post("/purchase-requests/{pr_id}/reject")
async def reject_purchase_request(pr_id: str, request: Request):
    from core.pr_approval import STAGE_LABELS, notify_requester
    user = await require_auth(request)
    db = get_db()
    doc, _chain, ev, _cfg = await _acc_ctx(db, pr_id, user)
    if doc.get("status") != "Submitted":
        raise HTTPException(400, "Tidak bisa ditolak pada status ini.")
    if not ev["can_reject"]:
        raise HTTPException(403, ev["blocked_reason"]
                            or "Akses ditolak: Anda tidak berhak menolak permintaan ini.")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    reason = (body.get("reason") or body.get("comment") or body.get("finance_notes") or "").strip()
    if not reason:
        raise HTTPException(400, "Alasan penolakan wajib diisi agar pemohon tahu "
                                 "apa yang harus diperbaiki.")
    label = f"Ditolak — {STAGE_LABELS.get(ev['stage'], ev['stage'] or '')}"
    if ev["is_override"]:
        label += " (override admin)"
    step = {
        "id": _id(), "step": ev["stage"], "stage": ev["stage"],
        "actor_id": user.get("id"),
        "actor_name": user.get("name", "") or user.get("email", ""),
        "actor_role": (user.get("role") or "").lower(),
        "action": "rejected", "action_label": label, "comment": reason,
        "override": bool(ev["is_override"]),
        "override_reasons": list(ev["override_reasons"]),
        "timestamp": _now_iso(),
    }
    await db.acc_purchase_requests.update_one({"id": pr_id}, {
        "$set": {"status": "Rejected", "finance_notes": reason,
                 "rejected_by": step["actor_name"], "rejected_at": _now_iso(),
                 "current_approver_stage": None, "updated_at": _now_iso()},
        "$push": {"approval_steps": step}})
    await notify_requester(
        db, {**doc, "status": "Rejected"}, severity="warning",
        module_id="proc-accessory-pr", number=doc.get("pr_number", ""),
        title="Request Pembelian Aksesoris Anda ditolak",
        body=(f"{doc.get('pr_number', '')} — {doc.get('purpose', '')}\n"
              f"Tahap: {STAGE_LABELS.get(ev['stage'], '-')}\nAlasan: {reason}"))
    return {"ok": True, "new_status": "Rejected", "override": bool(ev["is_override"])}



# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════

