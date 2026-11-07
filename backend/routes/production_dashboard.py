"""Dashboard Produksi — agregator satu panggilan yang mengikuti ALUR NYATA pabrik.

Kenyataan 2026 (dikonfirmasi owner): jahit dikerjakan vendor CMT di luar dan
Cutting sudah punya portal sendiri. Karena itu dashboard TIDAK lagi memakai
WIP per proses internal (Cutting→Sewing→Finishing→QC→Packing) yang sudah mati —
angkanya selalu nol dan menyesatkan.

Rantai yang benar:
    Rencana (PO) → Cutting → Di Vendor CMT → Terima & QC → Permak → Serah Terima FG

Satu endpoint dipakai dua portal:
    business_type=internal → Portal Produksi   (serah terima ke inventori sendiri)
    business_type=maklon   → Portal Maklon     (dispatch ke buyer)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from auth import require_auth
from database import get_db
from utils.waktu import today_wib, wib_date_of

router = APIRouter(prefix="/api/prod", tags=["production-dashboard"])

PLANNING_STATUSES = ["Draft", "Confirmed"]
ACTIVE_STATUSES = ["Draft", "Confirmed", "Distributed", "In Production",
                   "Production Complete", "Variance Review", "Return Review",
                   "Ready to Close"]
CLOSED_STATUSES = ["Closed", "Completed", "Closed Short"]
CUT_ACTIVE = ["draft", "in_progress"]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


async def _po_scope(db, business_type: str) -> tuple[list, dict]:
    """PO aktif untuk tipe bisnis ini + peta id→dokumen."""
    q = ({"business_type": "internal"} if business_type == "internal"
         else {"business_type": {"$ne": "internal"}})
    pos = await db.production_pos.find(q, {"_id": 0}).to_list(3000)
    return pos, {p["id"]: p for p in pos}


@router.get("/dashboard")
async def production_dashboard(
    business_type: str = Query("internal", pattern="^(internal|maklon)$"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(require_auth),
):
    db = get_db()
    since = (today_wib() - timedelta(days=days)).isoformat()
    pos, po_map = await _po_scope(db, business_type)
    po_ids = list(po_map.keys())

    # ── PO: hitung per status + qty dari po_items ────────────────────────────
    items = await db.po_items.find({"po_id": {"$in": po_ids}},
                                   {"_id": 0, "po_id": 1, "id": 1, "qty": 1}).to_list(20000)
    qty_by_po: dict[str, int] = {}
    item_ids: list[str] = []
    for it in items:
        qty_by_po[it["po_id"]] = qty_by_po.get(it["po_id"], 0) + _i(it.get("qty"))
        item_ids.append(it["id"])

    by_status: dict[str, dict] = {}
    for p in pos:
        st = p.get("status") or "Draft"
        row = by_status.setdefault(st, {"status": st, "count": 0, "qty": 0})
        row["count"] += 1
        row["qty"] += qty_by_po.get(p["id"], 0)
    po_status = sorted(by_status.values(), key=lambda r: -r["count"])

    aktif = [p for p in pos if p.get("status") in ACTIVE_STATUSES]
    qty_aktif = sum(qty_by_po.get(p["id"], 0) for p in aktif)
    qty_rencana = sum(qty_by_po.get(p["id"], 0) for p in pos if p.get("status") in PLANNING_STATUSES)

    # ── Cutting (portal sendiri, dipakai kedua tipe bisnis) ──────────────────
    from core.cutting_material_issue import ORDERS as _CUT_ORDERS  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
    cut_rows = await db[_CUT_ORDERS].aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1},
                    "planned": {"$sum": "$planned_output_qty"},
                    "produced": {"$sum": "$produced_qty"},
                    "consumed": {"$sum": "$consumed_input_qty"},
                    "waste": {"$sum": "$waste_qty"}}},
    ]).to_list(20)
    cut_by_status = {r["_id"]: r for r in cut_rows}
    # Tahap 1 (6 Nov 2026): kain/sisa/rendemen per SATUAN kain dan tanpa order batal
    # (dulu kg + yard dijumlah jadi satu angka). Satu rumus dengan dashboard Cutting.
    from routes.cutting import cutting_unit_totals
    cut_tot = await cutting_unit_totals(db)
    cutting = {
        "draft": _i(cut_by_status.get("draft", {}).get("n")),
        "in_progress": _i(cut_by_status.get("in_progress", {}).get("n")),
        "completed": _i(cut_by_status.get("completed", {}).get("n")),
        "qty_dalam_proses": round(sum(_f(cut_by_status.get(s, {}).get("planned")) for s in CUT_ACTIVE)),
        "qty_potongan_jadi": round(cut_tot["produced"]),
        "kain_terpakai": cut_tot["consumed"],
        "waste": cut_tot["waste"],
        "rendemen": cut_tot["yield"],
        "per_satuan": cut_tot["by_unit"],
        "panel_aktif": await db.rahaza_materials.count_documents({"is_cut_panel": True, "active": True}),
    }

    # ── Tahap 9 (7 Nov 2026): angka alur dari SATU sumber per baris PO (core.pantau_produksi) ──
    # Dulu "Di Vendor CMT" dikurangi kiriman berstatus `Received` — status itu berarti CMT SUDAH MENERIMA
    # BAHAN, bukan barang jadi kembali; QC membaca status lama (approved/draft) sehingga penerimaan
    # `completed_qc` tidak terhitung; serah terima ikut menjumlah deklarasi CMT→DA.
    from core import pantau_produksi as pp
    run_pos = [p for p in pos if not pp.po_closed(p) and not pp.po_cancelled(p)]
    lines = await pp.po_lines(db, run_pos)
    po_rows = pp.rollup_pos(run_pos, lines)
    tot = pp.sum_lines(lines)
    per_vendor: dict[str, dict] = {}
    for r in po_rows:
        name = r.get("vendor_name") or "(tanpa nama)"
        v = per_vendor.setdefault(name, {"vendor": name, "kirim": 0, "qty_kirim": 0, "qty_kembali": 0})
        v["kirim"] += 1 if r["sent_cmt"] else 0
        v["qty_kirim"] += r["sent_cmt"]
        v["qty_kembali"] += r["returned"] + r["in_qc"]
    for v in per_vendor.values():
        v["outstanding"] = max(0, v["qty_kirim"] - v["qty_kembali"])
    vendor = {
        "pengiriman": sum(v["kirim"] for v in per_vendor.values()),
        "qty_terkirim": tot["sent_cmt"],
        "qty_kembali": tot["returned"] + tot["in_qc"],
        "outstanding": tot["di_cmt"],
        "per_vendor": sorted((v for v in per_vendor.values() if v["qty_kirim"]),
                             key=lambda v: -v["outstanding"])[:8],
    }

    # ── Terima FG dari CMT + mutu (status kanonik; angka lolos/tolak dari baris PO) ──
    from core.cmt_receipt_status import canon_status, ST_QC, ST_DONE
    rq = {"business_type": "internal"} if business_type == "internal" else {"business_type": {"$ne": "internal"}}
    receipts = await db.cmt_receipts.find(rq, {"_id": 0, "id": 1, "status": 1, "approved_at": 1,
                                               "qc_completed_at": 1, "cmt_name": 1}).to_list(5000)
    today_iso = today_wib().isoformat()
    tested = tot["accepted"] + tot["reject"]
    qc = {"draft": 0, "submitted": sum(1 for r in receipts if canon_status(r.get("status")) == ST_QC),
          "approved": sum(1 for r in receipts if canon_status(r.get("status")) == ST_DONE), "rejected": 0,
          "qty_diterima": tot["accepted"], "qty_ditolak": tot["reject"], "pcs_hari_ini": 0,
          "menunggu_qty": tot["in_qc"],
          "vendor_aktif": len({r.get("cmt_name") for r in receipts if r.get("cmt_name")}),
          "tingkat_cacat": round(tot["reject"] / tested * 100, 2) if tested else 0.0}
    done_ids = {r["id"] for r in receipts if canon_status(r.get("status")) == ST_DONE
                and wib_date_of(r.get("qc_completed_at") or r.get("approved_at")) == today_iso}
    if done_ids:
        async for ln in db.cmt_receipt_lines.find({"receipt_id": {"$in": list(done_ids)}},
                                                  {"_id": 0, "qty_actual": 1}):
            qc["pcs_hari_ini"] += _i(ln.get("qty_actual"))

    # ── Permak / perbaikan — hanya PO portal ini ─────────────────────────────
    permak = {"terbuka": 0, "selesai": 0, "qty_terbuka": tot["reject_open"]}
    async for pm in db.dewi_cmt_permak.find({"po_id": {"$in": po_ids}}, {"_id": 0, "status": 1}):
        st = str(pm.get("status") or "").lower()
        if st in ("open", "in_progress"):
            permak["terbuka"] += 1
        else:
            permak["selesai"] += 1

    # ── Serah terima FG / kirim ke klien — HANYA surat jalan ke penerima akhir (SSOT) ──
    from core.dispatch_capacity import buyer_dispatch_items, item_dispatched
    rows_all = await buyer_dispatch_items(db, po_ids=po_ids) if po_ids else []
    # 2026-11-06 (pola P3): tanggal kirim ada di BARIS (`dispatch_date`, per kiriman bertahap).
    rows_recent = [r for r in rows_all if wib_date_of(r.get("dispatch_date") or r.get("created_at")) >= since]
    qty_recent = sum(item_dispatched(r) for r in rows_recent)
    recent_ids = {r.get("shipment_id") for r in rows_recent if r.get("shipment_id")}
    handover = {
        "pengiriman": len({r.get("shipment_id") for r in rows_all if r.get("shipment_id")}),
        "qty_total": sum(item_dispatched(r) for r in rows_all),
        "qty_periode": qty_recent,
        "label": "Serah terima ke gudang" if business_type == "internal" else "Kirim ke klien",
    }

    # ── Rantai tahap (untuk visual alur) ─────────────────────────────────────
    pipeline = [
        {"stage": "rencana", "label": "Rencana PO", "qty": qty_rencana,
         "count": sum(1 for p in pos if p.get("status") in PLANNING_STATUSES),
         "module": "prod-pos-internal" if business_type == "internal" else "maklon-pos-engine"},
        {"stage": "cutting", "label": "Cutting", "qty": cutting["qty_dalam_proses"],
         "count": cutting["draft"] + cutting["in_progress"], "module": "cutting-orders"},
        {"stage": "vendor", "label": "Di vendor CMT", "qty": vendor["outstanding"],
         "count": sum(1 for v in per_vendor.values() if v["outstanding"]), "module": "prod-shipments-vendor"},
        {"stage": "qc", "label": "Terima & QC", "qty": qc["menunggu_qty"],
         "count": qc["submitted"], "module": "da-cmt-receive"},
        {"stage": "permak", "label": "Permak", "qty": permak["qty_terbuka"],
         "count": permak["terbuka"], "module": "cmt-permak"},
        {"stage": "kirim", "label": handover["label"], "qty": handover["qty_periode"],
         "count": len(recent_ids),
         "module": "prod-shipments-buyer"},
    ]

    # ── PO tertahan paling lama (bukan bottleneck proses, tapi bottleneck alur) ──
    now = datetime.now(timezone.utc)
    aging = []
    for p in aktif:
        raw = p.get("updated_at") or p.get("created_at")
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            umur = (now - ts).days
        except (TypeError, ValueError):
            umur = 0
        aging.append({"po_id": p["id"], "po_number": p.get("po_number"),
                      "status": p.get("status"), "qty": qty_by_po.get(p["id"], 0),
                      "hari_diam": umur,
                      "deadline": str(p.get("deadline") or "")[:10] or None,
                      "customer": p.get("customer_name") or p.get("vendor_name") or ""})
    aging.sort(key=lambda r: -r["hari_diam"])

    return {
        "business_type": business_type,
        "periode_hari": days,
        "ringkasan": {
            "po_aktif": len(aktif),
            "qty_aktif": qty_aktif,
            "po_selesai": sum(1 for p in pos if p.get("status") in CLOSED_STATUSES),
            "di_vendor": vendor["outstanding"],
            "menunggu_qc": qc["menunggu_qty"],
            "tingkat_cacat": qc["tingkat_cacat"],
            "keluar_periode": handover["qty_periode"],
        },
        "pipeline": pipeline,
        "po_status": po_status,
        "cutting": cutting,
        "vendor": vendor,
        "qc": qc,
        "permak": permak,
        "handover": handover,
        "aging": aging[:8],
        "updated_at": now.isoformat(),
    }
