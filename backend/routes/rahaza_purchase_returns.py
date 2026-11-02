"""routes.rahaza_purchase_returns — Retur Pembelian (Pengadaan) & Nota Debit (Keuangan).

2026-11-02, keputusan owner K11 (audit g.md No.21). Model jurnal & alasannya: `core.purchase_returns`.
Router ini DIGABUNG ke router `routes.rahaza_ap_from_gr` (prefix /api/rahaza, satu pendaftaran di
server.py) — tidak menambah pendaftaran router baru.

  GET  /purchase-returns                          daftar (+ umur hari; ?status=awaiting_settlement)
  GET  /purchase-returns/{id}
  POST /purchase-returns                          buat draft — dari karantina atau stok; GR asal WAJIB
  POST /purchase-returns/{id}/send                kirim/proses: stok keluar + jurnal klaim barang bernilai
  POST /purchase-returns/{id}/receive-replacement tukar barang: pengganti datang
  POST /purchase-returns/{id}/refund              Keuangan: uang refund diterima
  POST /purchase-returns/{id}/cancel              batal (draft)
  POST /purchase-returns/{id}/repost              posting ulang jurnal yang gagal (mis. periode tertutup)
  GET  /debit-notes · GET /debit-notes/{id}
  POST /debit-notes                               Keuangan menerbitkan Nota Debit (menyelesaikan RTP)
  GET  /debit-notes/supplier-balances             saldo hutang per pemasok = faktur − nota debit
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from auth import log_activity, serialize_doc
from core import accessory_valuation, quarantine, stock_service
from core import purchase_returns as pr
from database import get_db
from utils.counters import gen_prefixed_number
from utils.waktu import today_wib, wib_date_str

log = logging.getLogger(__name__)
router = APIRouter(tags=["rahaza-purchase-returns"])

GR_DONE = ("received", "completed", "partial_received", "accepted")


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _actor(user: dict) -> dict:
    return {"id": user.get("id", ""), "name": user.get("name", ""), "email": user.get("email", "")}


def _date(v) -> date:
    try:
        return date.fromisoformat(str(v)[:10]) if v else today_wib()
    except ValueError:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD.")


# ── Gerbang akses ─────────────────────────────────────────────────────────────
async def _require_proc_wh(request: Request):
    """Pengadaan (pemilik dokumen) + gudang (tombol di Karantina / kirim fisik)."""
    from core.roles import FINANCE_ROLES
    from core.stock_rbac import DISPOSE_ROLES
    from routes.shared import PORTAL_ACCESS, require_perm
    return await require_perm(
        request, "proc.po.manage", "wh.receiving.manage", "fin.ap.manage",
        legacy_roles=tuple(PORTAL_ACCESS.get("procurement", ())) + tuple(DISPOSE_ROLES) + tuple(FINANCE_ROLES),
        message="Akses ditolak: Retur Pembelian dikelola Pengadaan/Gudang.")


async def _require_view(request: Request):
    from routes.rahaza_ap_from_gr import FINANCE_LEGACY_ROLES
    from core.stock_rbac import DISPOSE_ROLES
    from routes.shared import PORTAL_ACCESS, require_perm
    return await require_perm(
        request, "proc.po.view", "fin.ap.view", "wh.receiving.view", "proc.po.manage", "fin.ap.manage",
        legacy_roles=FINANCE_LEGACY_ROLES + tuple(PORTAL_ACCESS.get("procurement", ())) + tuple(DISPOSE_ROLES),
        message="Akses ditolak: butuh akses Pengadaan, Gudang, atau Keuangan.")


async def _require_fin(request: Request):
    from routes.rahaza_ap_from_gr import _require_finance
    return await _require_finance(request)


# ── Pembaca ───────────────────────────────────────────────────────────────────
async def _rtp_or_404(db, rid: str) -> dict:
    doc = await db[pr.RTP_COLL].find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Retur Pembelian tidak ditemukan.")
    return doc


async def _gr_or_400(db, gr_id: str) -> dict:
    gr = await db.warehouse_receiving.find_one({"id": gr_id}, {"_id": 0}) if gr_id else None
    if not gr:
        raise HTTPException(400, "GR asal wajib dipilih — harga & pemasok retur diambil dari penerimaan asal.")
    if gr.get("status") not in GR_DONE:
        raise HTTPException(400, f"GR {gr.get('receipt_number')} belum diterima (status '{gr.get('status')}').")
    return gr


def _gr_line(gr: dict, gr_item_id: str | None, material_id: str) -> dict:
    items = gr.get("items") or []
    line = next((li for li in items if gr_item_id and pr.line_id_of(li) == gr_item_id), None)
    if line is None:
        cands = [li for li in items if li.get("material_id") == material_id]
        line = cands[0] if len(cands) == 1 else None
    if line is None or line.get("material_id") != material_id:
        raise HTTPException(400, "Material retur tidak ada di GR asal (atau ada lebih dari satu baris — pilih baris GR).")
    return line


async def _ap_code_for_gr(db, gr: dict, line: dict) -> str | None:
    """Akun hutang faktur asal (sub-ledger pemasok) untuk nota debit setelah faktur."""
    inv_id = line.get("base_ap_invoice_id") or gr.get("ap_invoice_id")
    if not inv_id:
        return None
    inv = await db.rahaza_ap_invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        return None
    from routes.rahaza_posting import _ap_account_for_invoice
    from routes.rahaza_posting_profiles import get_mapping
    return await _ap_account_for_invoice(db, inv, (await get_mapping(db, "purchase_return")).get("ap"))


async def _check_roles(db, roles: set, kinds: set) -> None:
    """Pastikan peran profil yang AKAN dipakai terisi SEBELUM stok dimutasi (tidak ada mutasi
    setengah jadi karena profil kosong)."""
    from routes.rahaza_posting import inventory_account
    from routes.rahaza_posting_profiles import get_mapping
    m = await get_mapping(db, "purchase_return")
    missing = [r for r in roles if r not in ("inventory", "cash") and not str(m.get(r) or "").strip()]
    for k in kinds:
        code, err = inventory_account(m, "purchase_return", k)
        if not code:
            missing.append(err)
    if missing:
        raise HTTPException(400, "Profil Posting 'purchase_return' belum lengkap: " + "; ".join(missing))


async def _post_stage(db, rtp: dict, stage: str, lines: list, user: dict, *, je_date=None,
                      ap_code=None, cash_code=None, source_ref=None) -> dict:
    from routes.rahaza_posting import post_purchase_return
    ref = source_ref or f"rtp:{rtp['id']}:{stage}"
    memo = f"Retur Pembelian {rtp.get('rtp_number')} · {pr.SETTLEMENTS.get(rtp.get('settlement'), '')} · " \
           f"{rtp.get('supplier_name') or ''} · {stage}"
    try:
        res = await post_purchase_return(db, source_ref=ref, memo=memo, lines=lines, user=user,
                                         je_date=je_date, ap_code=ap_code, cash_code=cash_code)
    except Exception as e:  # noqa: BLE001
        log.exception("jurnal Retur Pembelian gagal")
        res = {"ok": False, "error": str(e)}
    entry = {"stage": stage, "source_ref": ref, "ok": bool(res.get("ok")), "je_number": res.get("je_number"),
             "skipped": bool(res.get("skipped")), "error": res.get("error"), "lines": lines,
             "ap_code": ap_code, "cash_code": cash_code, "at": _now()}
    await db[pr.RTP_COLL].update_one({"id": rtp["id"]}, {"$push": {"journals": entry}})
    return res


def _history(action: str, user: dict, note: str = "") -> dict:
    return {"action": action, "at": _now(), "by": user.get("name", ""), "by_id": user.get("id", ""), "note": note}


def _age_days(doc: dict) -> int:
    ts = doc.get("sent_at") or doc.get("created_at")
    if not ts:
        return 0
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (_now() - ts).days)


# ═════════════════════════════════════════════════════════════════════════════
# DAFTAR & DETAIL
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/purchase-returns")
async def list_purchase_returns(request: Request, status: str | None = None,
                                supplier_name: str | None = None, gr_id: str | None = None,
                                limit: int = Query(300, ge=1, le=1000)):
    await _require_view(request)
    db = get_db()
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    if gr_id:
        q["gr_id"] = gr_id
    if supplier_name:
        q["supplier_name"] = {"$regex": supplier_name, "$options": "i"}
    rows = await db[pr.RTP_COLL].find(q, {"_id": 0, "journals.lines": 0}).sort("created_at", -1).to_list(limit)
    for r in rows:
        r["age_days"] = _age_days(r)
        r["settlement_label"] = pr.SETTLEMENTS.get(r.get("settlement"), r.get("settlement"))
        r["status_label"] = pr.STATUS_LABELS.get(r.get("status"), r.get("status"))
    summary = {s: sum(1 for r in rows if r.get("status") == s) for s in pr.STATUS_LABELS}
    return {"items": serialize_doc(rows), "summary": summary, "settlements": pr.SETTLEMENTS}


@router.get("/purchase-returns/{rid}")
async def get_purchase_return(rid: str, request: Request):
    await _require_view(request)
    db = get_db()
    doc = await _rtp_or_404(db, rid)
    doc["age_days"] = _age_days(doc)
    doc["settlement_label"] = pr.SETTLEMENTS.get(doc.get("settlement"))
    doc["status_label"] = pr.STATUS_LABELS.get(doc.get("status"))
    return serialize_doc(doc)


# ═════════════════════════════════════════════════════════════════════════════
# BUAT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/purchase-returns", status_code=201)
async def create_purchase_return(request: Request):
    """Body: {settlement, destroy_borne_by?, gr_id?, reason, notes?, photos?[], ship_date?,
    lines: [{quarantine_item_id? | (material_id + location_id), qty, gr_item_id?, reason?}]}
    atau pintasan karantina {quarantine_item_id, qty}."""
    user = await _require_proc_wh(request)
    db = get_db()
    body = await request.json()
    settlement = body.get("settlement")
    if settlement not in pr.SETTLEMENTS:
        raise HTTPException(400, "Pilih penyelesaian: " + ", ".join(f"{k} ({v})" for k, v in pr.SETTLEMENTS.items()))
    borne_by = body.get("destroy_borne_by") if settlement == "destroy" else None
    if settlement == "destroy" and borne_by not in pr.BORNE_BY:
        raise HTTPException(400, "Barang dimusnahkan: pilih siapa yang menanggung (supplier / da).")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Alasan retur wajib diisi.")
    lines_in = list(body.get("lines") or [])
    if not lines_in and body.get("quarantine_item_id"):
        lines_in = [{"quarantine_item_id": body["quarantine_item_id"], "qty": body.get("qty"),
                     "gr_item_id": body.get("gr_item_id")}]
    if not lines_in:
        raise HTTPException(400, "Minimal satu baris retur.")

    gr_id = body.get("gr_id") or None
    qloc = await quarantine.get_quarantine_location_id(db)
    staged = []
    for ln in lines_in:
        qty = _f(ln.get("qty"))
        if qty <= 0:
            raise HTTPException(400, "Qty retur harus > 0.")
        if ln.get("quarantine_item_id"):
            qi = await db[quarantine.QUARANTINE_COLL].find_one({"id": ln["quarantine_item_id"]}, {"_id": 0})
            if not qi or qi.get("status") != "open":
                raise HTTPException(400, "Item karantina tidak ditemukan / sudah ditutup.")
            if qty - _f(qi.get("remaining_qty")) > 1e-6:
                raise HTTPException(400, f"Qty {qty:g} melebihi sisa karantina {_f(qi.get('remaining_qty')):g}.")
            src = qi.get("source") or {}
            src_gr = src.get("id") if src.get("type") in ("goods_receipt", "grn_inspection") else None
            if src_gr:
                if gr_id and gr_id != src_gr:
                    raise HTTPException(400, "Satu Retur Pembelian hanya untuk satu GR asal.")
                gr_id = src_gr
            vq, uq = quarantine.split_valued(qty, await quarantine.valued_remaining(db, qi))
            staged.append({"source": "quarantine", "quarantine_item_id": qi["id"], "material_id": qi["material_id"],
                           "qty": qty, "gr_item_id": ln.get("gr_item_id") or (src.get("line_id") if src_gr else None),
                           "reason": ln.get("reason") or reason, "valued_est": vq, "unvalued_est": uq})
        else:
            mid, loc = ln.get("material_id"), ln.get("location_id")
            if not mid or not loc:
                raise HTTPException(400, "Baris dari stok wajib material_id + location_id (lokasi asal).")
            if loc == qloc:
                raise HTTPException(400, "Barang di karantina diretur lewat item karantinanya, bukan dari stok.")
            row = await db[stock_service.STOCK].find_one({"material_id": mid, "location_id": loc}, {"_id": 0}) or {}
            avail = _f(row.get("qty")) - _f(row.get("reserved_quantity"))
            if qty - avail > 1e-6:
                raise HTTPException(400, f"Stok tersedia di lokasi itu {avail:g} — kurang dari qty retur {qty:g}.")
            staged.append({"source": "stock", "location_id": loc, "material_id": mid, "qty": qty,
                           "gr_item_id": ln.get("gr_item_id"), "reason": ln.get("reason") or reason,
                           "valued_est": qty, "unvalued_est": 0.0})
    gr = await _gr_or_400(db, gr_id)
    if settlement == "refund" and any(s["unvalued_est"] > 0 for s in staged):
        raise HTTPException(400, "Refund hanya untuk barang yang sudah masuk nilai persediaan/ditagih. Reject saat "
                                 "penerimaan belum pernah ditagih — pilih tukar barang atau potong tagihan.")
    from routes.rahaza_posting import inventory_kind
    lines = []
    for s in staged:
        li = _gr_line(gr, s["gr_item_id"], s["material_id"])
        price = pr.gr_line_price(li)
        if price <= 0:
            raise HTTPException(400, f"Baris GR {li.get('material_name') or s['material_id']} tidak berharga — "
                                     "harga retur diambil dari GR asal.")
        mat = await db.rahaza_materials.find_one({"id": s["material_id"]}, {"_id": 0}) or {}
        lines.append({
            "id": pr._uid(), "source": s["source"], "quarantine_item_id": s.get("quarantine_item_id"),
            "location_id": s.get("location_id"), "gr_item_id": pr.line_id_of(li), "po_item_id": li.get("po_item_id"),
            "material_id": s["material_id"], "material_code": mat.get("code") or li.get("sku"),
            "material_name": mat.get("name") or li.get("material_name"), "unit": li.get("unit") or mat.get("unit"),
            "kind": inventory_kind(mat), "qty": round(s["qty"], 4), "gr_price": price,
            "amount": round(s["qty"] * price, 2), "reason": s["reason"],
            "valued_qty_est": s["valued_est"], "unvalued_qty_est": s["unvalued_est"]})
    rtp = {
        "id": pr._uid(),
        "rtp_number": await gen_prefixed_number(db, pr.RTP_COLL, "rtp_number", f"RTP-{_now():%Y%m}-", 4),
        "status": "draft", "settlement": settlement, "destroy_borne_by": borne_by,
        "supplier_name": gr.get("supplier_name"), "supplier_id": gr.get("supplier_id"),
        "supplier_code": gr.get("supplier_code"),
        "gr_id": gr["id"], "gr_number": gr.get("receipt_number"), "po_id": gr.get("po_id"),
        "po_number": gr.get("po_number"), "lines": lines,
        "total_qty": round(sum(ln["qty"] for ln in lines), 4),
        "total_amount": round(sum(ln["amount"] for ln in lines), 2),
        "ppn_amount": 0.0,  # DA bukan PKP (K11) — tidak ada nota retur PPN
        "reason": reason, "notes": body.get("notes") or "", "photos": list(body.get("photos") or []),
        "ship_date": body.get("ship_date") or None, "journals": [],
        "history": [_history("create", user, f"{pr.SETTLEMENTS[settlement]} · {reason}")],
        "created_at": _now(), "updated_at": _now(),
        "created_by": user.get("id"), "created_by_name": user.get("name", ""),
    }
    await db[pr.RTP_COLL].insert_one(dict(rtp))
    await log_activity(user.get("id", ""), user.get("name", ""), "create", "purchase_return",
                       f"{rtp['rtp_number']} {pr.SETTLEMENTS[settlement]} · GR {gr.get('receipt_number')}")
    return serialize_doc(rtp)


# ═════════════════════════════════════════════════════════════════════════════
# KIRIM / PROSES (stok keluar)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/purchase-returns/{rid}/send")
async def send_purchase_return(rid: str, request: Request):
    """Barang keluar gudang (dikirim ke pemasok, atau dimusnahkan). Body: {ship_date?, notes?}"""
    user = await _require_proc_wh(request)
    db = get_db()
    body = await request.json() if await request.body() else {}
    rtp = await _rtp_or_404(db, rid)
    if rtp.get("status") != "draft":
        raise HTTPException(400, f"Retur {rtp.get('rtp_number')} sudah {pr.STATUS_LABELS.get(rtp.get('status'))}.")
    settlement = rtp.get("settlement")
    if settlement not in pr.SHIPPING_SETTLEMENTS:
        raise HTTPException(400, "Diterima dengan diskon: barang tidak dikirim — Keuangan menyelesaikannya lewat Nota Debit.")
    destroy_da = settlement == "destroy" and rtp.get("destroy_borne_by") == "da"
    await _check_roles(db, {"supplier_claim", "price_variance", "grni", "scrap_expense"},
                       {ln.get("kind") or "bahan" for ln in rtp["lines"]})
    actor = _actor(user)
    # validasi SEMUA baris dulu — tidak ada baris yang keluar bila satu baris tidak cukup
    for ln in rtp["lines"]:
        q = _f(ln["qty"])
        if ln["source"] == "quarantine":
            qi = await db[quarantine.QUARANTINE_COLL].find_one({"id": ln["quarantine_item_id"]}, {"_id": 0})
            if not qi or qi.get("status") != "open" or q - _f(qi.get("remaining_qty")) > 1e-6:
                raise HTTPException(400, f"Item karantina {ln.get('material_code')} sudah berubah — sisa tidak cukup.")
        else:
            row = await db[stock_service.STOCK].find_one(
                {"material_id": ln["material_id"], "location_id": ln["location_id"]}, {"_id": 0}) or {}
            if q - (_f(row.get("qty")) - _f(row.get("reserved_quantity"))) > 1e-6:
                raise HTTPException(400, f"Stok {ln.get('material_code')} di lokasi asal tidak cukup untuk {q:g}.")
    je_lines, late_list, out_lines = [], [], []
    for ln in rtp["lines"]:
        mat = await db.rahaza_materials.find_one({"id": ln["material_id"]}, {"_id": 0}) or {}
        wac = accessory_valuation.resolve_unit_cost(mat)
        qty = _f(ln["qty"])
        desc = f"{rtp['rtp_number']} {ln.get('material_code') or ''} {qty:g} {ln.get('unit') or ''}".strip()
        extra = {"purchase_return_id": rid, "rtp_number": rtp["rtp_number"]}
        if ln["source"] == "quarantine":
            qi = await db[quarantine.QUARANTINE_COLL].find_one({"id": ln["quarantine_item_id"]}, {"_id": 0})
            if not qi or qi.get("status") != "open" or qty - _f(qi.get("remaining_qty")) > 1e-6:
                raise HTTPException(400, f"Item karantina {ln.get('material_code')} sudah berubah — sisa tidak cukup.")
            vbefore = await quarantine.valued_remaining(db, qi)
            vq, uq = quarantine.split_valued(qty, vbefore)
            action = quarantine.ACTION_SCRAP if settlement == "destroy" else quarantine.ACTION_PURCHASE_RETURN
            try:
                await quarantine.quarantine_out(db, item=qi, action=action, qty=qty, actor=actor,
                                                notes=f"Retur Pembelian {rtp['rtp_number']}", extra=extra)
            except ValueError as e:
                raise HTTPException(400, str(e))
            await db[quarantine.QUARANTINE_COLL].update_one(
                {"id": qi["id"]}, {"$set": {"valued_qty": round(vbefore - vq, 4)}})
        else:
            vq, uq = qty, 0.0
            try:
                await stock_service.issue(ln["material_id"], ln["location_id"], qty,
                                          ref={"source": "purchase_return", "ref_type": "purchase_return",
                                               "ref_id": rid, "ref_number": rtp["rtp_number"]},
                                          actor=actor, db=db)
            except stock_service.InsufficientStock as e:
                raise HTTPException(400, f"Stok {ln.get('material_code')} di lokasi asal tidak cukup: {e}")
            from routes.rahaza_inventory_shared import _log_movement
            await _log_movement(db, user, type="issue", material_id=ln["material_id"], qty=qty,
                                from_location_id=ln["location_id"], to_location_id=None,
                                ref_type="purchase_return", ref_id=rid, unit_cost=wac,
                                notes=f"Retur Pembelian {rtp['rtp_number']}")
        plan = pr.plan_send(settlement=settlement, borne_by=rtp.get("destroy_borne_by"), valued_qty=vq,
                            unvalued_qty=uq, gr_price=ln["gr_price"], wac=wac, kind=ln.get("kind") or "bahan",
                            desc=desc)
        je_lines += plan["lines"]
        if plan["late_billable"]:
            late_list.append((ln, plan["late_billable"]))
        out_lines.append({**ln, "valued_qty": vq, "unvalued_qty": uq, "wac_at_send": round(wac, 4),
                          "claim_amount": plan["claim_amount"], "unvalued_amount": round(uq * ln["gr_price"], 2)})
    new_status = "settled" if destroy_da else "awaiting_settlement"
    await db[pr.RTP_COLL].update_one({"id": rid}, {
        "$set": {"lines": out_lines, "status": new_status, "sent_at": _now(), "sent_by": user.get("name", ""),
                 "ship_date": body.get("ship_date") or rtp.get("ship_date") or wib_date_str(),
                 "total_claim_amount": round(sum(x["claim_amount"] for x in out_lines), 2),
                 "settled_at": _now() if destroy_da else None, "updated_at": _now()},
        "$push": {"history": _history("destroy" if settlement == "destroy" else "send", user, body.get("notes") or "")}})
    rtp = await _rtp_or_404(db, rid)
    posting = await _post_stage(db, rtp, "send", je_lines, user)
    for ln, lb in late_list:   # musnah ditanggung DA atas reject GR → bisa ditagih pemasok
        await pr.record_late_receipt(db, gr_id=rtp["gr_id"], line_id=ln["gr_item_id"], qty=lb["qty"],
                                     unit_price=lb["unit_price"], source="rtp_destroy_da", ref_id=rid,
                                     ref_number=rtp["rtp_number"], je_number=posting.get("je_number"), actor=user)
    await log_activity(user.get("id", ""), user.get("name", ""), "send", "purchase_return",
                       f"{rtp['rtp_number']} → {new_status}")
    out = await _rtp_or_404(db, rid)
    out["_posting"] = {k: posting.get(k) for k in ("ok", "je_number", "error", "skipped")}
    return serialize_doc(out)


# ═════════════════════════════════════════════════════════════════════════════
# PENYELESAIAN
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/purchase-returns/{rid}/receive-replacement")
async def receive_replacement(rid: str, request: Request):
    """Tukar barang: pengganti datang. Body: {location_id, notes?}. Bagian bernilai menutup klaim
    (Dr persediaan / Cr klaim); bagian reject GR = penerimaan susulan (Dr persediaan / Cr GRNI,
    bisa ditagih). HPP rata-rata diperbarui pada harga GR."""
    user = await _require_proc_wh(request)
    db = get_db()
    body = await request.json()
    rtp = await _rtp_or_404(db, rid)
    if rtp.get("settlement") != "exchange" or rtp.get("status") != "awaiting_settlement":
        raise HTTPException(400, "Hanya Retur tukar barang yang sudah dikirim yang bisa menerima pengganti.")
    loc = body.get("location_id")
    from core import location_resolver
    if not loc or not await location_resolver.location_exists(db, loc):
        raise HTTPException(400, "location_id wajib — pilih lokasi penerima barang pengganti.")
    await _check_roles(db, {"supplier_claim"}, {ln.get("kind") or "bahan" for ln in rtp["lines"]})
    gr = await _gr_or_400(db, rtp["gr_id"])
    actor = _actor(user)
    je_lines, lates = [], []
    for ln in rtp["lines"]:
        qty, price = _f(ln["qty"]), _f(ln["gr_price"])
        qty_before = await quarantine.valued_onhand(db, ln["material_id"])
        await stock_service.add(ln["material_id"], loc, qty,
                                meta={"unit": ln.get("unit"), "material_code": ln.get("material_code"),
                                      "material_name": ln.get("material_name")},
                                ref={"source": "purchase_return_replacement", "ref_id": rid,
                                     "ref_number": rtp["rtp_number"]}, actor=actor, db=db)
        vq, uq = _f(ln.get("valued_qty")), _f(ln.get("unvalued_qty"))
        if vq > 0:
            from routes.rahaza_inventory_shared import _log_movement
            await _log_movement(db, user, type="receive", material_id=ln["material_id"], qty=vq,
                                to_location_id=loc, from_location_id=None, unit_cost=price,
                                ref_type="purchase_return_replacement", ref_id=rid,
                                notes=f"Pengganti Retur Pembelian {rtp['rtp_number']} (jurnal: purchase_return)")
            je_lines += pr.plan_replacement_valued(vq, price, ln.get("kind") or "bahan",
                                                   f"{rtp['rtp_number']} pengganti {ln.get('material_code')}")
        if uq > 0:
            line = _gr_line(gr, ln.get("gr_item_id"), ln["material_id"])
            lates.append(await pr.receive_late(db, gr=gr, line=line, qty=uq, unit_price=price, location_id=loc,
                                               source="rtp_replacement", ref_id=rid, ref_number=rtp["rtp_number"],
                                               user=user, apply_wac=False))
            gr = await _gr_or_400(db, rtp["gr_id"])
        await accessory_valuation.apply_receipt_cost(
            db, ln["material_id"], qty, price, qty_before=qty_before, actor=actor,
            notes=f"Pengganti Retur Pembelian {rtp['rtp_number']}")
    await db[pr.RTP_COLL].update_one({"id": rid}, {
        "$set": {"status": "settled", "settled_at": _now(), "replacement_location_id": loc, "updated_at": _now()},
        "$push": {"history": _history("receive_replacement", user, body.get("notes") or "")}})
    posting = await _post_stage(db, rtp, "replacement", je_lines, user)
    out = await _rtp_or_404(db, rid)
    out["_posting"] = {k: posting.get(k) for k in ("ok", "je_number", "error", "skipped")}
    out["_late_postings"] = [{k: (x.get("posting") or {}).get(k) for k in ("ok", "je_number", "error")} for x in lates]
    return serialize_doc(out)


@router.post("/purchase-returns/{rid}/refund")
async def record_refund(rid: str, request: Request):
    """Keuangan: uang refund dari pemasok diterima. Body: {cash_account_id, date?, notes?}
    Dr kas/bank (akun GL rekening) / Cr klaim retur sebesar klaim (harga GR)."""
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    rtp = await _rtp_or_404(db, rid)
    if rtp.get("settlement") != "refund" or rtp.get("status") != "awaiting_settlement":
        raise HTTPException(400, "Hanya Retur refund yang sudah dikirim yang bisa dicatat refund-nya.")
    acc = await db.rahaza_cash_accounts.find_one({"id": body.get("cash_account_id")}, {"_id": 0}) \
        if body.get("cash_account_id") else None
    if not acc or not acc.get("gl_account_code"):
        raise HTTPException(400, "Pilih rekening kas/bank penerima refund (yang punya akun GL).")
    await _check_roles(db, {"supplier_claim"}, set())
    amount = round(_f(rtp.get("total_claim_amount")), 2)
    posting = await _post_stage(db, rtp, "refund", pr.plan_refund(amount, f"Refund {rtp['rtp_number']}"), user,
                                je_date=_date(body.get("date")), cash_code=acc["gl_account_code"])
    if not posting.get("ok"):
        raise HTTPException(400, f"Jurnal refund gagal: {posting.get('error')}")
    await db[pr.RTP_COLL].update_one({"id": rid}, {
        "$set": {"status": "settled", "settled_at": _now(), "refund_amount": amount,
                 "refund_cash_account_id": acc["id"], "refund_je_number": posting.get("je_number"),
                 "updated_at": _now()},
        "$push": {"history": _history("refund", user, f"Rp {amount:,.0f} → {acc.get('name')}")}})
    return serialize_doc(await _rtp_or_404(db, rid))


@router.post("/purchase-returns/{rid}/cancel")
async def cancel_purchase_return(rid: str, request: Request):
    user = await _require_proc_wh(request)
    db = get_db()
    body = await request.json() if await request.body() else {}
    rtp = await _rtp_or_404(db, rid)
    if rtp.get("status") != "draft":
        raise HTTPException(400, "Hanya Retur berstatus Draft yang bisa dibatalkan (barang belum keluar).")
    await db[pr.RTP_COLL].update_one({"id": rid}, {
        "$set": {"status": "cancelled", "cancelled_at": _now(), "updated_at": _now()},
        "$push": {"history": _history("cancel", user, body.get("reason") or "")}})
    return serialize_doc(await _rtp_or_404(db, rid))


@router.post("/purchase-returns/{rid}/repost")
async def repost_purchase_return(rid: str, request: Request):
    """Posting ulang tahap jurnal yang gagal (mis. periode tertutup sudah dibuka)."""
    user = await _require_fin(request)
    db = get_db()
    rtp = await _rtp_or_404(db, rid)
    done = {j["source_ref"] for j in rtp.get("journals") or [] if j.get("ok")}
    out = []
    for j in rtp.get("journals") or []:
        if j.get("ok") or j["source_ref"] in done:
            continue
        res = await _post_stage(db, rtp, j["stage"], j.get("lines") or [], user, ap_code=j.get("ap_code"),
                                cash_code=j.get("cash_code"), source_ref=j["source_ref"])
        if res.get("ok"):
            done.add(j["source_ref"])
        out.append({"stage": j["stage"], "ok": res.get("ok"), "je_number": res.get("je_number"),
                    "error": res.get("error")})
    return {"reposted": out}


# ═════════════════════════════════════════════════════════════════════════════
# NOTA DEBIT (Keuangan)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/debit-notes")
async def list_debit_notes(request: Request, supplier_name: str | None = None,
                           limit: int = Query(300, ge=1, le=1000)):
    await _require_view(request)
    db = get_db()
    q: dict = {}
    if supplier_name:
        q["supplier_name"] = {"$regex": supplier_name, "$options": "i"}
    rows = await db[pr.DN_COLL].find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"items": serialize_doc(rows)}


@router.get("/debit-notes/supplier-balances")
async def supplier_balances(request: Request):
    """Saldo hutang per pemasok = sisa faktur − nota debit yang mengurangi hutang (K11).
    Nota debit sebelum faktur mengurangi GRNI (tagihan dari GR otomatis lebih kecil) — tidak dihitung
    di sini. Faktur yang dibayar penuh lalu terkena nota debit ⇒ saldo negatif = pemasok berutang ke DA."""
    await _require_view(request)
    db = get_db()
    out: dict = {}

    def slot(name, sid):
        key = (sid or (name or "").strip().lower())
        return out.setdefault(key, {"supplier_id": sid, "supplier_name": name, "invoice_balance": 0.0,
                                    "invoice_count": 0, "debit_note_ap": 0.0, "debit_note_count": 0})
    async for inv in db.rahaza_ap_invoices.find(
            {"status": {"$nin": ["draft", "cancelled", "void", "written_off"]}}, {"_id": 0}):
        s = slot(inv.get("vendor_name"), inv.get("supplier_id"))
        s["invoice_balance"] += _f(inv.get("balance"))
        s["invoice_count"] += 1
    async for dn in db[pr.DN_COLL].find({"status": "issued"}, {"_id": 0}):
        s = slot(dn.get("supplier_name"), dn.get("supplier_id"))
        s["debit_note_ap"] += _f(dn.get("ap_amount"))
        s["debit_note_count"] += 1
    rows = []
    for s in out.values():
        s["invoice_balance"] = round(s["invoice_balance"], 2)
        s["debit_note_ap"] = round(s["debit_note_ap"], 2)
        s["net_payable"] = round(s["invoice_balance"] - s["debit_note_ap"], 2)
        rows.append(s)
    rows.sort(key=lambda r: -abs(r["net_payable"]))
    return {"items": rows, "total_net_payable": round(sum(r["net_payable"] for r in rows), 2)}


@router.get("/debit-notes/{dn_id}")
async def get_debit_note(dn_id: str, request: Request):
    await _require_view(request)
    db = get_db()
    dn = await db[pr.DN_COLL].find_one({"id": dn_id}, {"_id": 0})
    if not dn:
        raise HTTPException(404, "Nota Debit tidak ditemukan.")
    return serialize_doc(dn)


@router.post("/debit-notes", status_code=201)
async def issue_debit_note(request: Request):
    """Keuangan menerbitkan Nota Debit atas Retur Pembelian (menyelesaikannya).

    Body: {purchase_return_id, date?, notes?, disc_price? (diterima dengan diskon), to_location_id?
    (diterima dengan diskon dari karantina — lokasi penyimpanan barang yang diterima)}."""
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    rtp = await _rtp_or_404(db, body.get("purchase_return_id") or "")
    st = rtp.get("settlement")
    if st not in pr.DEBIT_NOTE_SETTLEMENTS or (st == "destroy" and rtp.get("destroy_borne_by") != "supplier"):
        raise HTTPException(400, "Nota Debit hanya untuk retur potong tagihan, diterima dengan diskon, atau "
                                 "dimusnahkan atas tanggungan pemasok.")
    want = "draft" if st == "accept_discount" else "awaiting_settlement"
    if rtp.get("status") != want:
        raise HTTPException(400, f"Retur {rtp.get('rtp_number')} berstatus {pr.STATUS_LABELS.get(rtp.get('status'))} — "
                                 + ("barang belum dikirim/diproses." if want == "awaiting_settlement" else "sudah diproses."))
    gr = await _gr_or_400(db, rtp["gr_id"])
    dn_date = _date(body.get("date"))
    kinds = {ln.get("kind") or "bahan" for ln in rtp["lines"]}
    disc = None
    to_loc = body.get("to_location_id")
    if st == "accept_discount":
        if body.get("disc_price") in (None, ""):
            raise HTTPException(400, "Harga setelah diskon (disc_price) wajib diketik Keuangan.")
        disc = _f(body.get("disc_price"))
        if disc < 0 or any(disc - _f(ln["gr_price"]) > 1e-9 for ln in rtp["lines"]):
            raise HTTPException(400, "Harga diskon harus ≥ 0 dan tidak lebih tinggi dari harga GR.")
        if any(ln["source"] == "quarantine" for ln in rtp["lines"]):
            from core import location_resolver
            if not to_loc or not await location_resolver.location_exists(db, to_loc):
                raise HTTPException(400, "to_location_id wajib — barang karantina yang diterima disimpan di mana?")
    await _check_roles(db, {"supplier_claim", "grni", "ap", "price_variance"}, kinds)

    dn_id = pr._uid()
    dn_number = await gen_prefixed_number(db, pr.DN_COLL, "dn_number", f"ND-{_now():%Y%m}-", 4)
    actor = _actor(user)
    je_lines, dn_lines, lates = [], [], []
    ap_amount = grni_amount = info_amount = 0.0
    ap_code = None
    out_lines = []
    for ln in rtp["lines"]:
        line = _gr_line(gr, ln.get("gr_item_id"), ln["material_id"])
        billed = pr.base_billed(gr, line)
        if billed and not ap_code:
            ap_code = await _ap_code_for_gr(db, gr, line)
        H, qty = _f(ln["gr_price"]), _f(ln["qty"])
        desc = f"{dn_number} · {rtp['rtp_number']} {ln.get('material_code') or ''}"
        if st in ("debit_note", "destroy"):
            claim = _f(ln.get("claim_amount"))
            je_lines += pr.plan_debit_note(claim, billed=billed, desc=desc)
            if claim > 0 and not billed:
                await pr.add_billing_deduction(db, gr_id=gr["id"], line_id=pr.line_id_of(line),
                                               qty=_f(ln.get("valued_qty")), amount=claim, source="debit_note",
                                               ref_id=dn_id, ref_number=dn_number)
                gr = await _gr_or_400(db, rtp["gr_id"])
            ap_amount += claim if billed else 0.0
            grni_amount += 0.0 if billed else claim
            info_amount += _f(ln.get("unvalued_amount"))
            dn_lines.append({"material_code": ln.get("material_code"), "material_name": ln.get("material_name"),
                             "qty": qty, "unit": ln.get("unit"), "price": H, "amount": round(qty * H, 2),
                             "basis": "bernilai" if claim > 0 else "reject GR (belum ditagih)"})
            out_lines.append(ln)
            continue
        # ── diterima dengan diskon ──
        if ln["source"] == "quarantine":
            qi = await db[quarantine.QUARANTINE_COLL].find_one({"id": ln["quarantine_item_id"]}, {"_id": 0})
            if not qi or qi.get("status") != "open" or qty - _f(qi.get("remaining_qty")) > 1e-6:
                raise HTTPException(400, f"Item karantina {ln.get('material_code')} sudah berubah — sisa tidak cukup.")
            vbefore = await quarantine.valued_remaining(db, qi)
            vq, uq = quarantine.split_valued(qty, vbefore)
            qty_before = await quarantine.valued_onhand(db, ln["material_id"])
            try:
                await quarantine.quarantine_out(db, item=qi, action=quarantine.ACTION_RELEASE, qty=qty,
                                                to_location_id=to_loc, actor=actor,
                                                notes=f"Diterima dengan diskon {dn_number}",
                                                extra={"purchase_return_id": rtp["id"], "rtp_number": rtp["rtp_number"],
                                                       "unit_price": disc})
            except ValueError as e:
                raise HTTPException(400, str(e))
            await db[quarantine.QUARANTINE_COLL].update_one(
                {"id": qi["id"]}, {"$set": {"valued_qty": round(vbefore - vq, 4)}})
            if uq > 0:
                lates.append(await pr.receive_late(db, gr=gr, line=line, qty=uq, unit_price=disc, location_id=to_loc,
                                                   source="rtp_accept_discount", ref_id=rtp["id"],
                                                   ref_number=f"{rtp['rtp_number']} / {dn_number}", user=user,
                                                   qty_before=qty_before))
                gr = await _gr_or_400(db, rtp["gr_id"])
        else:
            vq, uq = qty, 0.0
        cut = round(vq * (H - disc), 2)
        absorbed = False
        if cut > 0:
            res = await accessory_valuation.apply_value_change(
                db, ln["material_id"], -cut, actor=actor, notes=f"Potongan harga {dn_number}")
            absorbed = bool(res.get("applied"))
            je_lines += pr.plan_discount_valued(vq, H, disc, billed=billed, absorbed=absorbed,
                                                kind=ln.get("kind") or "bahan", desc=desc)
            if not billed:
                await pr.add_billing_deduction(db, gr_id=gr["id"], line_id=pr.line_id_of(line), qty=0.0, amount=cut,
                                               source="accept_discount", ref_id=dn_id, ref_number=dn_number)
                gr = await _gr_or_400(db, rtp["gr_id"])
            ap_amount += cut if billed else 0.0
            grni_amount += 0.0 if billed else cut
        info_amount += round(uq * (H - disc), 2)
        dn_lines.append({"material_code": ln.get("material_code"), "material_name": ln.get("material_name"),
                         "qty": qty, "unit": ln.get("unit"), "price": H, "disc_price": disc,
                         "amount": round(qty * (H - disc), 2),
                         "basis": "potongan harga barang diterima"})
        out_lines.append({**ln, "valued_qty": vq, "unvalued_qty": uq, "disc_price": disc,
                          "discount_absorbed_by_stock": absorbed})
    total = round(sum(x["amount"] for x in dn_lines), 2)
    dn = {"id": dn_id, "dn_number": dn_number, "date": dn_date.isoformat(), "status": "issued",
          "purchase_return_id": rtp["id"], "rtp_number": rtp["rtp_number"], "settlement": st,
          "supplier_name": rtp.get("supplier_name"), "supplier_id": rtp.get("supplier_id"),
          "gr_id": rtp["gr_id"], "gr_number": rtp.get("gr_number"), "po_number": rtp.get("po_number"),
          "lines": dn_lines, "total_amount": total, "ppn_amount": 0.0, "ppn_note": "DA bukan PKP — tanpa PPN retur",
          "ap_amount": round(ap_amount, 2), "grni_amount": round(grni_amount, 2), "info_amount": round(info_amount, 2),
          "notes": body.get("notes") or "", "created_at": _now(), "created_by": user.get("id"),
          "created_by_name": user.get("name", "")}
    posting = await _post_stage(db, rtp, "debit_note", je_lines, user, je_date=dn_date, ap_code=ap_code,
                                source_ref=f"dn:{dn_id}")
    dn.update({"je_id": posting.get("je_id"), "je_number": posting.get("je_number"),
               "gl_error": None if posting.get("ok") else posting.get("error")})
    await db[pr.DN_COLL].insert_one(dict(dn))
    await db[pr.RTP_COLL].update_one({"id": rtp["id"]}, {
        "$set": {"status": "settled", "settled_at": _now(), "debit_note_id": dn_id, "debit_note_number": dn_number,
                 "lines": out_lines, "updated_at": _now()},
        "$push": {"history": _history("debit_note", user, f"{dn_number} Rp {total:,.0f}")}})
    await log_activity(user.get("id", ""), user.get("name", ""), "issue", "debit_note",
                       f"{dn_number} atas {rtp['rtp_number']} Rp {total:,.0f}")
    dn["_late_postings"] = [{k: (x.get("posting") or {}).get(k) for k in ("ok", "je_number", "error")} for x in lates]
    return serialize_doc(dn)
