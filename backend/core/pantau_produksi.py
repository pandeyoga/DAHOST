"""core.pantau_produksi — SATU sumber angka layar Pantau Produksi, Dashboard, dan Laporan Selisih.

Tahap 9 (keputusan owner 7 Nov 2026, no. 7 & 11). Lima layar lama (Production Jobs, Tracking
Produksi/Vendor, Tracking Order, Monitoring CMT, Pusat Kendali) masing-masing menghitung sendiri
dan angkanya berbeda di layar yang sama:

* "Di Vendor CMT" dikurangi kiriman berstatus `Received` — status itu berarti CMT SUDAH MENERIMA
  BAHAN, bukan barang jadi sudah kembali (Dashboard).
* "Dikirim ke Buyer" menjumlah SEMUA `buyer_shipment_items`, termasuk deklarasi CMT→DA (Production
  Jobs; Dashboard menghitung deklarasi itu sebagai serah terima).
* Laporan selisih dihitung per JOB, sehingga kekurangan yang sudah ditutup job tambahan tetap
  terbaca kurang; baris yang belum dikonfirmasi klien dianggap diterima penuh.
* Pusat Kendali, Monitoring CMT, dan Kapasitas tidak disaring per jenis PO.

Modul ini menghitung angka PER BARIS PO (po_item) sekali, dari dokumen sumber, lalu semua tab
(Ringkasan, Per vendor, Per PO, Kejar CMT, Kapasitas) dan Laporan Selisih menjumlahkannya.
Angka hilir produksi (produksi, QC, permak, kirim) DIAMBIL dari SSOT `core.dispatch_capacity.
po_item_quantities` — modul ini hanya menambah sisi bahan (potongan dikirim, diterima CMT) yang
belum ada di sana. Tidak menulis apa pun.

Saringan portal (aturan yang paling banyak dipakai): internal = ``business_type == 'internal'``,
maklon = ``business_type != 'internal'``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

BT_INTERNAL, BT_MAKLON = "internal", "maklon"
PO_CLOSED = {"completed", "complete", "closed", "closed short", "cancelled", "canceled", "selesai",
             "batal", "done", "finished", "archived"}
PO_CANCELLED = {"cancelled", "canceled", "batal"}
CLOSED_SHORT = "Closed Short"
EXTRA_LABEL = {"REPLACEMENT": "Pengganti", "ADDITIONAL": "Tambahan", "REWORK": "Permak ke CMT"}
STATE_LABEL = {"belum": "Belum mulai", "jalan": "Berjalan", "selesai": "Selesai QC", "ditutup": "Ditutup"}


# ─── util ────────────────────────────────────────────────────────────────────
def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_date(v) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        from utils.waktu import wib_date_of
        s = wib_date_of(v)
        return date.fromisoformat(s) if s else None
    except Exception:  # noqa: BLE001
        try:
            return date.fromisoformat(str(v)[:10])
        except (TypeError, ValueError):
            return None


def norm_bt(bt: Optional[str]) -> str:
    """'internal' | 'maklon' | '' (semua). Kata lain (toko, generic) dianggap maklon."""
    s = str(bt or "").strip().lower()
    if not s or s in ("all", "semua"):
        return ""
    return BT_INTERNAL if s == BT_INTERNAL else BT_MAKLON


def bt_filter(bt: Optional[str]) -> Dict[str, Any]:
    b = norm_bt(bt)
    if b == BT_INTERNAL:
        return {"business_type": BT_INTERNAL}
    if b == BT_MAKLON:
        return {"business_type": {"$ne": BT_INTERNAL}}
    return {}


def bt_of(po: Dict[str, Any]) -> str:
    return BT_INTERNAL if (po or {}).get("business_type") == BT_INTERNAL else BT_MAKLON


def po_closed(po: Dict[str, Any]) -> bool:
    return str((po or {}).get("status") or "").strip().lower() in PO_CLOSED


def po_cancelled(po: Dict[str, Any]) -> bool:
    return str((po or {}).get("status") or "").strip().lower() in PO_CANCELLED


def po_deadline(po: Dict[str, Any]) -> Optional[date]:
    """Batas kirim ke pemesan diutamakan (deadline mitra/klien), lalu batas internal."""
    return _to_date((po or {}).get("delivery_deadline")) or _to_date((po or {}).get("deadline"))


def shipment_kind(ship: Optional[dict], item: Optional[dict] = None) -> str:
    from services.cmt_kejar import shipment_kind as _kind
    return _kind(ship, item)


# ─── memuat PO ──────────────────────────────────────────────────────────────
async def load_pos(db, bt: Optional[str] = None, *, running: Optional[bool] = None,
                   po_ids: Optional[Iterable[str]] = None, vendor_id: str = "",
                   limit: int = 3000) -> List[Dict[str, Any]]:
    """PO produksi menurut portal. `running=True` = belum selesai/ditutup/batal; PO batal selalu dibuang."""
    q: Dict[str, Any] = dict(bt_filter(bt))
    if po_ids is not None:
        q["id"] = {"$in": [p for p in po_ids if p]}
    if vendor_id:
        q["vendor_id"] = vendor_id
    pos = await db.production_pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    pos = [p for p in pos if not po_cancelled(p)]
    if running is True:
        pos = [p for p in pos if not po_closed(p)]
    elif running is False:
        pos = [p for p in pos if po_closed(p)]
    return pos


# ─── sisi BAHAN: potongan dikirim ke CMT & diterima CMT ─────────────────────
async def material_by_item(db, po_item_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """{po_item_id: {...}} — potongan dikirim (NORMAL vs tambahan) dan hasil periksa bahan di CMT."""
    ids = [p for p in dict.fromkeys(po_item_ids or []) if p]
    out: Dict[str, Dict[str, Any]] = {
        p: {"sent_cmt": 0, "sent_extra": 0, "sent_extra_by_type": {}, "material_received": 0,
            "material_missing": 0, "material_uninspected": 0, "material_notes": [],
            "first_sent": None, "shipments": []} for p in ids}
    if not ids:
        return out
    vsi = await db.vendor_shipment_items.find({"po_item_id": {"$in": ids}}, {"_id": 0}).to_list(None)
    ship_ids = list({v.get("shipment_id") for v in vsi if v.get("shipment_id")})
    ships: Dict[str, dict] = {}
    if ship_ids:
        for s in await db.vendor_shipments.find({"id": {"$in": ship_ids}}, {"_id": 0}).to_list(None):
            ships[s["id"]] = s
    vsi_ids = [v["id"] for v in vsi if v.get("id")]
    insp: Dict[str, dict] = {}
    if vsi_ids:
        rows = await db.vendor_material_inspection_items.find(
            {"shipment_item_id": {"$in": vsi_ids}}, {"_id": 0}).to_list(None)
        # periksa ulang: yang terakhir berlaku (bukan dijumlah dua kali)
        for ii in sorted(rows, key=lambda r: str(r.get("created_at") or "")):
            insp[ii["shipment_item_id"]] = ii
    for v in vsi:
        r = out.get(v.get("po_item_id"))
        if r is None:
            continue
        s = ships.get(v.get("shipment_id")) or {}
        qty = _i(v.get("qty_sent"))
        kind = shipment_kind(s, v)
        if kind == "NORMAL":
            r["sent_cmt"] += qty
        else:
            r["sent_extra"] += qty
            r["sent_extra_by_type"][kind] = r["sent_extra_by_type"].get(kind, 0) + qty
        d = _to_date(s.get("shipment_date") or v.get("created_at"))
        if kind == "NORMAL" and d and (r["first_sent"] is None or d < r["first_sent"]):
            r["first_sent"] = d
        ii = insp.get(v.get("id"))
        if ii:
            r["material_received"] += _i(ii.get("received_qty"))
            miss = _i(ii.get("missing_qty"))
            r["material_missing"] += miss
            note = (ii.get("condition_notes") or "").strip()
            if miss and note:
                r["material_notes"].append(note)
        else:
            r["material_uninspected"] += qty
        r["shipments"].append({"shipment_id": v.get("shipment_id"),
                               "shipment_number": s.get("shipment_number") or v.get("shipment_number") or "",
                               "kind": kind, "qty_sent": qty,
                               "received": _i(ii.get("received_qty")) if ii else None,
                               "missing": _i(ii.get("missing_qty")) if ii else None,
                               "date": d.isoformat() if d else None})
    for r in out.values():
        r["first_sent"] = r["first_sent"].isoformat() if r["first_sent"] else None
    return out


# ─── angka per BARIS PO ─────────────────────────────────────────────────────
def line_state(row: Dict[str, Any]) -> str:
    """Status satu baris dari angka nyata — Selesai berarti LOLOS QC ≥ dipesan (bukan diproduksi)."""
    started = row["sent_cmt"] + row["sent_extra"] + row["produced"] + row["accepted"] + row["in_qc"]
    if row["ordered"] > 0 and row["accepted"] >= row["ordered"]:
        return "selesai"
    return "jalan" if started > 0 else "belum"


def build_line(po: dict, item: dict, q: dict, m: dict) -> Dict[str, Any]:
    """Gabungkan SSOT hilir (`q`) + sisi bahan (`m`) menjadi satu baris (fungsi murni)."""
    bt = bt_of(po)
    ordered = _i(q.get("ordered")) or _i(item.get("qty"))
    sent_cmt = _i(m.get("sent_cmt"))
    # setoran CMT yang menutup potongan: klaim penerimaan selesai QC, tanpa barang hasil permak di CMT
    returned = max(0, _i(q.get("claimed")) - _i(q.get("repaired_cmt")))
    in_qc = _i(q.get("in_qc"))
    accepted = _i(q.get("accepted_total"))
    received_confirmed = _i(q.get("received_confirmed"))
    price = _f(item.get("cmt_price_snapshot"))
    row = {
        "po_item_id": item.get("id"), "po_id": po.get("id"), "po_number": po.get("po_number") or "",
        "business_type": bt, "vendor_id": po.get("vendor_id") or "", "vendor_name": po.get("vendor_name") or "",
        "customer_name": po.get("customer_name") or "",
        "serial_number": item.get("serial_number") or q.get("serial_number") or "",
        "sku": item.get("sku") or q.get("sku") or "", "product_name": item.get("product_name") or "",
        "size": item.get("size") or "", "color": item.get("color") or "",
        "ordered": ordered,
        "not_sent": max(0, ordered - sent_cmt),
        "sent_cmt": sent_cmt, "sent_extra": _i(m.get("sent_extra")),
        "sent_extra_by_type": dict(m.get("sent_extra_by_type") or {}),
        "material_received": _i(m.get("material_received")), "material_missing": _i(m.get("material_missing")),
        "material_uninspected": _i(m.get("material_uninspected")),
        "produced": _i(q.get("produced_main")), "rework_produced": _i(q.get("rework_produced")),
        "returned": returned, "in_qc": in_qc,
        "di_cmt": max(0, sent_cmt - returned - in_qc),
        "arrived": _i(q.get("arrived_fresh")), "good_from_cmt": _i(q.get("good_from_cmt")),
        "reject": _i(q.get("reject")), "repaired": _i(q.get("repaired")), "scrap": _i(q.get("scrap")),
        "reject_open": _i(q.get("reject_open")),
        "rework_open": _i(q.get("rework_open_da")) + _i(q.get("rework_open_cmt")),
        "cmt_short_open": _i(q.get("cmt_short_open")),
        "accepted": accepted,
        "dispatched": _i(q.get("dispatched")), "shipped": _i(q.get("shipped")),
        "received_confirmed": received_confirmed, "pending_confirm": _i(q.get("pending_receipt")),
        "buyer_short_open": _i(q.get("buyer_short_open")),
        "shippable": _i(q.get("shippable")), "over_dispatched": _i(q.get("over_dispatched")),
        # hasil akhir rantai: internal = masuk stok barang jadi (lolos QC); maklon = diterima klien
        "final": accepted if bt == BT_INTERNAL else received_confirmed,
        "receipt_ids": list(q.get("receipt_ids") or []),
        "cmt_cost": round(price * _i(q.get("good_from_cmt")), 2),
        "first_sent": m.get("first_sent"),
        "material_notes": list(m.get("material_notes") or []),
        "shipments": list(m.get("shipments") or []),
    }
    row["state"] = line_state(row)
    return row


async def po_lines(db, pos: List[dict]) -> List[Dict[str, Any]]:
    """Semua baris PO untuk daftar PO — satu putaran kueri (bukan per PO)."""
    from core import dispatch_capacity as dcap
    po_by_id = {p["id"]: p for p in pos if p.get("id")}
    if not po_by_id:
        return []
    items = await db.po_items.find({"po_id": {"$in": list(po_by_id)}}, {"_id": 0}).to_list(None)
    ids = [it["id"] for it in items if it.get("id")]
    q = await dcap.po_item_quantities(db, ids)
    m = await material_by_item(db, ids)
    out = []
    for it in items:
        po = po_by_id.get(it.get("po_id"))
        if po is None or not it.get("id"):
            continue
        out.append(build_line(po, it, q.get(it["id"]) or {}, m.get(it["id"]) or {}))
    out.sort(key=lambda r: (r["po_number"], r["serial_number"], r["sku"], r["size"]))
    return out


SUM_FIELDS = ("ordered", "not_sent", "sent_cmt", "sent_extra", "material_received", "material_missing",
              "material_uninspected", "produced", "rework_produced", "returned", "in_qc", "di_cmt", "arrived",
              "good_from_cmt", "reject", "repaired", "scrap", "reject_open", "rework_open", "cmt_short_open",
              "accepted", "dispatched", "shipped", "received_confirmed", "pending_confirm", "buyer_short_open",
              "shippable", "over_dispatched", "final", "cmt_cost")


def sum_lines(rows: Iterable[dict]) -> Dict[str, Any]:
    tot: Dict[str, Any] = {f: 0 for f in SUM_FIELDS}
    extra: Dict[str, int] = {}
    receipts: set = set()
    for r in rows or []:
        for f in SUM_FIELDS:
            tot[f] += r.get(f) or 0
        for k, v in (r.get("sent_extra_by_type") or {}).items():
            extra[k] = extra.get(k, 0) + v
        receipts.update(r.get("receipt_ids") or [])
    tot["cmt_cost"] = round(tot["cmt_cost"], 2)
    tot["sent_extra_by_type"] = extra
    tot["receipt_count"] = len(receipts)
    return tot


def progress_pct(t: dict) -> float:
    return round(t["accepted"] / t["ordered"] * 100, 1) if t.get("ordered") else 0.0


def po_state(po: dict, lines: List[dict]) -> str:
    if po_closed(po):
        return "ditutup"
    if not lines or all(r["state"] == "belum" for r in lines):
        return "belum"
    if all(r["state"] == "selesai" for r in lines):
        return "selesai"
    return "jalan"


def risk_of(po: dict, t: dict, today: date) -> Dict[str, Any]:
    """Telat / berisiko (aturan Pusat Kendali lama): telat = lewat batas kirim; berisiko = ≤5 hari & <70%,
    atau ≤2 hari. PO yang sudah lolos QC penuh atau sudah ditutup tidak dihitung."""
    dl = po_deadline(po)
    days = (dl - today).days if dl else None
    pct = progress_pct(t)
    if po_closed(po) or (t.get("ordered") and t["accepted"] >= t["ordered"]):
        risk = "aman"
    elif days is None:
        risk = "tanpa_deadline"
    elif days < 0:
        risk = "telat"
    elif (days <= 5 and pct < 70) or days <= 2:
        risk = "berisiko"
    else:
        risk = "aman"
    return {"deadline": dl.isoformat() if dl else None, "days_to_deadline": days, "risk": risk,
            "progress_pct": pct}


def rollup_pos(pos: List[dict], lines: List[dict], today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Baris per PO = jumlah baris PO-nya (tanpa rumus kedua)."""
    from utils.waktu import today_wib
    today = today or today_wib()
    by_po: Dict[str, list] = {}
    for r in lines:
        by_po.setdefault(r["po_id"], []).append(r)
    out = []
    for po in pos:
        ls = by_po.get(po["id"], [])
        t = sum_lines(ls)
        out.append({
            "po_id": po["id"], "po_number": po.get("po_number") or "", "business_type": bt_of(po),
            "status": po.get("status") or "", "customer_name": po.get("customer_name") or "",
            "vendor_id": po.get("vendor_id") or "", "vendor_name": po.get("vendor_name") or "",
            "po_date": str(po.get("po_date") or po.get("created_at") or "")[:10] or None,
            "closed_reason": po.get("closed_reason") or "", "close_notes": po.get("close_notes") or "",
            "line_count": len(ls), "state": po_state(po, ls), **t, **risk_of(po, t, today),
        })
    return out


# ─── pemeriksa keseimbangan (menyebut PO penyebab) ──────────────────────────
BALANCE_RULES = (
    # (kunci, label, kiri, kanan, PO pecah bila …) — bawaan: kiri ≠ kanan
    ("order", "Dipesan = Belum dikirim ke CMT + Potongan ke CMT",
     lambda t: t["ordered"], lambda t: t["not_sent"] + t["sent_cmt"], None),
    ("cmt", "Potongan ke CMT = Masih di CMT + Sedang QC + Disetor CMT",
     lambda t: t["sent_cmt"], lambda t: t["di_cmt"] + t["in_qc"] + t["returned"], None),
    ("produksi", "Sampai di DA tidak melebihi yang diproduksi CMT",
     lambda t: t["arrived"], lambda t: t["produced"],
     lambda t: t["produced"] > 0 and t["arrived"] > t["produced"]),
    ("reject", "Ditolak QC = Permak berhasil + Dibuang + Belum jelas",
     lambda t: t["reject"], lambda t: t["repaired"] + t["scrap"] + t["reject_open"], None),
    ("kirim", "Lolos QC = Sudah dikirim + Sisa bisa dikirim",
     lambda t: t["accepted"], lambda t: t["dispatched"] + t["shippable"], None),
)


def balance_checks(po_rows: List[dict], limit: int = 20) -> Dict[str, Any]:
    """Lima identitas yang membuat angka tidak bisa 'mengarang'. Yang pecah menyebut PO penyebabnya."""
    checks = []
    for key, label, left_fn, right_fn, bad_fn in BALANCE_RULES:
        left = right = 0
        offenders = []
        for t in po_rows:
            lv, rv = left_fn(t), right_fn(t)
            left += lv
            right += rv
            if (bad_fn(t) if bad_fn else lv != rv):
                offenders.append({"po_id": t["po_id"], "po_number": t["po_number"], "left": lv, "right": rv,
                                  "diff": lv - rv})
        checks.append({"key": key, "label": label, "left": left, "right": right, "diff": left - right,
                       "ok": not offenders, "offenders": offenders[:limit], "offender_count": len(offenders)})
    return {"checks": checks, "all_ok": all(c["ok"] for c in checks)}


# ─── ringkasan (tab Ringkasan Pantau Produksi + Dashboard) ──────────────────
async def _cutting_block(db) -> Dict[str, Any]:
    """Order potong tidak terikat PO (stok potongan) — sama untuk kedua portal."""
    try:
        from core.cutting_material_issue import ORDERS
        from routes.cutting import cutting_unit_totals
        rows = await db[ORDERS].find({"status": {"$in": ["draft", "in_progress"]}},
                                     {"_id": 0, "status": 1, "planned_output_qty": 1}).to_list(5000)
        tot = await cutting_unit_totals(db)
        return {"orders_open": len(rows), "qty_dalam_proses": round(sum(_f(r.get("planned_output_qty")) for r in rows)),
                "qty_potongan_jadi": round(_f(tot.get("produced"))), "per_satuan": tot.get("by_unit") or []}
    except Exception:  # noqa: BLE001 — cutting pelengkap; ringkasan tetap tampil
        return {"orders_open": 0, "qty_dalam_proses": 0, "qty_potongan_jadi": 0, "per_satuan": []}


async def _qc_done_windows(db, po_item_ids: List[str], today: date, days: int) -> Dict[str, int]:
    """Pcs lolos QC yang selesai diperiksa hari ini dan dalam N hari terakhir."""
    from core.cmt_receipt_status import is_done
    out = {"today": 0, "window": 0}
    if not po_item_ids:
        return out
    lines = await db.cmt_receipt_lines.find({"po_item_id": {"$in": po_item_ids}},
                                            {"_id": 0, "receipt_id": 1, "qty_actual": 1}).to_list(None)
    rids = list({ln.get("receipt_id") for ln in lines if ln.get("receipt_id")})
    when: Dict[str, Optional[date]] = {}
    if rids:
        async for rc in db.cmt_receipts.find({"id": {"$in": rids}}, {"_id": 0}):
            if is_done(rc.get("status")):
                when[rc["id"]] = _to_date(rc.get("qc_completed_at") or rc.get("approved_at") or rc.get("receipt_date"))
    since = today - timedelta(days=days)
    for ln in lines:
        d = when.get(ln.get("receipt_id"))
        if not d:
            continue
        if d == today:
            out["today"] += _i(ln.get("qty_actual"))
        if d >= since:
            out["window"] += _i(ln.get("qty_actual"))
    return out


async def _jobs_summary(db, po_ids: List[str], today: date, days: int) -> Dict[str, Any]:
    """Job jahit induk per status (pengganti 'Status WO' Pusat Kendali) + selesai hari ini / N hari."""
    from core.production_job_lifecycle import JOB_CLOSED_STATUSES
    out = {"belum": 0, "jalan": 0, "selesai": 0, "selesai_hari_ini": 0, "selesai_periode": 0}
    if not po_ids:
        return out
    jobs = await db.production_jobs.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(None)
    jobs = [j for j in jobs if not j.get("parent_job_id")]
    jids = [j["id"] for j in jobs if j.get("id")]
    prod: Dict[str, int] = {}
    if jids:
        async for ji in db.production_job_items.find({"job_id": {"$in": jids}}, {"_id": 0, "job_id": 1, "produced_qty": 1}):
            prod[ji["job_id"]] = prod.get(ji["job_id"], 0) + _i(ji.get("produced_qty"))
    since = today - timedelta(days=days)
    for j in jobs:
        st = str(j.get("status") or "")
        if st.lower() == "cancelled":
            continue
        if st in JOB_CLOSED_STATUSES or st.lower() in ("completed", "closed", "done"):
            out["selesai"] += 1
            d = _to_date(j.get("closed_at") or j.get("completed_at") or j.get("updated_at"))
            if d == today:
                out["selesai_hari_ini"] += 1
            if d and d >= since:
                out["selesai_periode"] += 1
        elif prod.get(j["id"], 0) > 0:
            out["jalan"] += 1
        else:
            out["belum"] += 1
    return out


async def _open_counts(db, po_ids: List[str]) -> Dict[str, int]:
    """Dokumen yang masih terbuka di tiap tahap (untuk kolom 'dokumen' alur)."""
    from core.cmt_receipt_status import canon_status, ST_QC
    out = {"receipts_qc": 0, "permak_open": 0}
    if not po_ids:
        return out
    async for rc in db.cmt_receipts.find({"po_id": {"$in": po_ids}}, {"_id": 0, "status": 1}):
        if canon_status(rc.get("status")) == ST_QC:
            out["receipts_qc"] += 1
    out["permak_open"] = await db.dewi_cmt_permak.count_documents(
        {"po_id": {"$in": po_ids}, "status": {"$in": ["open", "in_progress"]}})
    return out


async def _costs(db, po_ids: List[str], cmt_cost: float) -> Dict[str, Any]:
    """Biaya yang tampil di Ringkasan pemilik lama: ongkos jahit terhitung, biaya permak, komponen kurang —
    hanya PO portal ini (dulu permak & komponen kurang tidak disaring)."""
    from services.cmt_kejar import COMPONENT_OPEN_STATUSES
    out = {"ongkos_jahit": round(cmt_cost or 0, 2), "biaya_permak": 0.0, "permak_aktif": 0,
           "komponen_kurang": 0, "komponen_kurang_qty": 0}
    if not po_ids:
        return out
    async for pm in db.dewi_cmt_permak.find({"po_id": {"$in": po_ids}}, {"_id": 0, "total_cost": 1, "status": 1}):
        out["biaya_permak"] += _f(pm.get("total_cost"))
        if pm.get("status") in ("open", "in_progress"):
            out["permak_aktif"] += 1
    async for c in db.dewi_cmt_component_requests.find(
            {"po_id": {"$in": po_ids}, "status": {"$in": list(COMPONENT_OPEN_STATUSES)}}, {"_id": 0, "items": 1}):
        out["komponen_kurang"] += 1
        out["komponen_kurang_qty"] += sum(_i(it.get("qty")) for it in (c.get("items") or []))
    out["biaya_permak"] = round(out["biaya_permak"], 2)
    return out


async def duplicate_serials(db, bt: Optional[str]) -> Dict[str, Any]:
    from services.cmt_intake import cek_seri
    scope = {BT_INTERNAL: "internal", BT_MAKLON: "maklon"}.get(norm_bt(bt), "all")
    res = await cek_seri(db, scope=scope)
    return {"count": res.get("duplicate_count", 0), "items": (res.get("duplicates") or [])[:30]}


async def ringkasan(db, bt: Optional[str], *, days: int = 7, today: Optional[date] = None) -> Dict[str, Any]:
    """Tab Ringkasan + Dashboard: alur barang, keseimbangan, telat, selesai, deadline ≤14 hari, seri dobel."""
    from utils.waktu import today_wib
    today = today or today_wib()
    b = norm_bt(bt) or BT_INTERNAL
    pos = await load_pos(db, b, running=True)
    lines = await po_lines(db, pos)
    po_rows = rollup_pos(pos, lines, today)
    t = sum_lines(lines)
    po_ids = [p["id"] for p in pos]
    open_docs = await _open_counts(db, po_ids)
    cutting = await _cutting_block(db)
    vendors_at_cmt = {r["vendor_id"] or r["vendor_name"] for r in po_rows if r["di_cmt"] > 0}
    final_label = "Masuk stok barang jadi" if b == BT_INTERNAL else "Diterima klien"
    send_label = "Diserahkan ke gudang" if b == BT_INTERNAL else "Dikirim ke klien"
    alur = [
        {"key": "rencana", "label": "Belum dikirim ke CMT", "qty": t["not_sent"],
         "docs": sum(1 for r in po_rows if r["not_sent"] > 0), "doc_label": "PO", "module": "prod-shipments-vendor"},
        {"key": "cutting", "label": "Sedang dipotong", "qty": cutting["qty_dalam_proses"],
         "docs": cutting["orders_open"], "doc_label": "order potong", "module": "cutting-orders",
         "note": "Semua order potong, tidak dipisah per PO"},
        {"key": "vendor", "label": "Di vendor CMT", "qty": t["di_cmt"], "docs": len(vendors_at_cmt),
         "doc_label": "vendor", "module": "pantau-produksi"},
        {"key": "qc", "label": "Sedang diperiksa (QC)", "qty": t["in_qc"], "docs": open_docs["receipts_qc"],
         "doc_label": "penerimaan", "module": "da-cmt-receive"},
        {"key": "permak", "label": "Ditolak QC, belum selesai", "qty": t["reject_open"], "docs": open_docs["permak_open"],
         "doc_label": "permak", "module": "cmt-permak"},
        {"key": "siap", "label": "Lolos QC, belum dikirim", "qty": t["shippable"],
         "docs": sum(1 for r in po_rows if r["shippable"] > 0), "doc_label": "PO", "module": "prod-shipments-buyer"},
        {"key": "kirim", "label": send_label, "qty": t["dispatched"],
         "docs": sum(1 for r in po_rows if r["dispatched"] > 0), "doc_label": "PO", "module": "prod-shipments-buyer"},
    ]
    if b == BT_MAKLON:
        alur.append({"key": "konfirmasi", "label": "Belum dikonfirmasi klien", "qty": t["pending_confirm"],
                     "docs": sum(1 for r in po_rows if r["pending_confirm"] > 0), "doc_label": "PO",
                     "module": "prod-shipments-buyer"})
    overdue = sorted([r for r in po_rows if r["risk"] in ("telat", "berisiko")],
                     key=lambda r: (r["risk"] != "telat", r["days_to_deadline"] if r["days_to_deadline"] is not None else 999))
    upcoming = sorted([r for r in po_rows if r["days_to_deadline"] is not None and 0 <= r["days_to_deadline"] <= 14
                       and r["state"] != "selesai"], key=lambda r: r["days_to_deadline"])
    aging = []
    from datetime import timezone
    now = datetime.now(timezone.utc)
    for p in pos:
        raw = p.get("updated_at") or p.get("created_at")
        try:
            ts = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            idle = (now - ts).days
        except (TypeError, ValueError):
            idle = 0
        aging.append({"po_id": p["id"], "po_number": p.get("po_number") or "", "status": p.get("status") or "",
                      "idle_days": idle, "customer_name": p.get("customer_name") or "",
                      "vendor_name": p.get("vendor_name") or ""})
    aging.sort(key=lambda r: -r["idle_days"])
    qc_done = await _qc_done_windows(db, [r["po_item_id"] for r in lines], today, days)
    jobs = await _jobs_summary(db, po_ids, today, days)
    tested = t["accepted"] + t["reject"]
    return {
        "business_type": b, "as_of": today.isoformat(), "window_days": days,
        "final_label": final_label,
        "kpi": {"po_berjalan": len(pos), "qty_berjalan": t["ordered"], "di_cmt": t["di_cmt"], "in_qc": t["in_qc"],
                "telat": sum(1 for r in po_rows if r["risk"] == "telat"),
                "berisiko": sum(1 for r in po_rows if r["risk"] == "berisiko"),
                "reject_rate": round(t["reject"] / tested * 100, 1) if tested else 0.0,
                "progress_pct": progress_pct(t)},
        "totals": t,
        "alur": alur,
        "balance": balance_checks(po_rows),
        "overdue": overdue[:30],
        "upcoming": upcoming[:30],
        "aging": aging[:10],
        "done": {"qc_today": qc_done["today"], "qc_window": qc_done["window"],
                 "jobs_today": jobs["selesai_hari_ini"], "jobs_window": jobs["selesai_periode"]},
        "jobs": {k: jobs[k] for k in ("belum", "jalan", "selesai")},
        "duplicate_serials": await duplicate_serials(db, b),
        "cutting": cutting,
        "biaya": await _costs(db, po_ids, t["cmt_cost"]),
    }


# ─── per PO (tab Per PO) ────────────────────────────────────────────────────
def _match(text: str, *vals) -> bool:
    s = (text or "").strip().lower()
    return not s or any(s in str(v or "").lower() for v in vals)


async def per_po(db, bt: Optional[str], *, search: str = "", state: str = "", running: Optional[bool] = None,
                 today: Optional[date] = None) -> Dict[str, Any]:
    """Tabel per PO + baris seri → SKU (RowDetail). Cari: PO, vendor, seri, SKU. Status: belum/jalan/selesai/ditutup."""
    b = norm_bt(bt) or BT_INTERNAL
    pos = await load_pos(db, b, running=running)
    lines = await po_lines(db, pos)
    rows = rollup_pos(pos, lines, today)
    by_po: Dict[str, list] = {}
    for ln in lines:
        by_po.setdefault(ln["po_id"], []).append(ln)
    counts = {k: 0 for k in STATE_LABEL}
    out = []
    for r in rows:
        ls = by_po.get(r["po_id"], [])
        hit_lines = [ln for ln in ls if _match(search, ln["serial_number"], ln["sku"], ln["product_name"])]
        if search and not (_match(search, r["po_number"], r["vendor_name"], r["customer_name"]) or hit_lines):
            continue
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        if state and r["state"] != state:
            continue
        shown = ls if (not search or _match(search, r["po_number"], r["vendor_name"], r["customer_name"])) else hit_lines
        out.append({**r, "lines": shown, "line_match": len(shown) if search else None})
    return {"business_type": b, "count": len(out), "counts": counts, "rows": out}


# ─── per vendor (tab Per vendor CMT) ────────────────────────────────────────
async def per_vendor(db, bt: Optional[str], *, running: Optional[bool] = True,
                     today: Optional[date] = None) -> Dict[str, Any]:
    """Satu baris per vendor (jumlah baris PO-nya) + job & QC per job untuk RowDetail."""
    from routes.production_execution import _enrich_jobs
    from routes.production_rbac import resolve_vendor_doc
    from utils.waktu import today_wib
    today = today or today_wib()
    b = norm_bt(bt) or BT_INTERNAL
    pos = await load_pos(db, b, running=running)
    lines = await po_lines(db, pos)
    po_rows = rollup_pos(pos, lines, today)
    po_ids = [p["id"] for p in pos]
    jobs = await db.production_jobs.find({"po_id": {"$in": po_ids}}, {"_id": 0}).sort("created_at", -1).to_list(5000) \
        if po_ids else []
    parents = [j for j in jobs if not j.get("parent_job_id")]
    enriched = await _enrich_jobs(db, parents) if parents else []
    po_by_id = {p["id"]: p for p in pos}
    groups: Dict[str, Dict[str, Any]] = {}

    def _g(vid: str, vname: str) -> Dict[str, Any]:
        key = vid or "internal"
        return groups.setdefault(key, {"vendor_id": vid, "vendor_name": vname or ("Dijahit sendiri" if not vid else ""),
                                       "vendor_code": "", "po_rows": [], "jobs": [], "pending_pos": []})
    for r in po_rows:
        g = _g(r["vendor_id"], r["vendor_name"])
        g["po_rows"].append(r)
    for j in enriched:
        po = po_by_id.get(j.get("po_id")) or {}
        g = _g(j.get("vendor_id") or po.get("vendor_id") or "", j.get("vendor_name") or po.get("vendor_name") or "")
        dl = _to_date(j.get("deadline") or j.get("delivery_deadline")) or po_deadline(po)
        g["jobs"].append({
            "id": j.get("id"), "job_number": j.get("job_number") or "", "po_id": j.get("po_id"),
            "po_number": j.get("po_number") or po.get("po_number") or "",
            "serial_numbers": j.get("serial_numbers") or [], "status": j.get("status") or "",
            "deadline": dl.isoformat() if dl else None,
            "ordered": _i(j.get("total_ordered")), "available": _i(j.get("total_available")),
            "produced": _i(j.get("total_produced")), "accepted": _i(j.get("total_accepted")),
            "reject": _i(j.get("total_reject")), "rework_open": _i(j.get("total_rework_open")),
            "repaired": _i(j.get("total_repaired")), "scrap": _i(j.get("total_scrap")),
            "reject_rate_pct": j.get("reject_rate_pct") or 0,
            "progress_pct": j.get("progress_pct") or 0,
            "entry_source": j.get("progress_entry_source") or "none",
            "staff_qty": _i(j.get("staff_entered_progress_qty")),
            "staff_by": j.get("staff_entered_by") or [],
            "child_jobs": j.get("child_jobs") or [],
        })
    with_job = {j.get("po_id") for j in parents}
    for r in po_rows:
        if r["po_id"] not in with_job:
            _g(r["vendor_id"], r["vendor_name"])["pending_pos"].append(
                {"po_id": r["po_id"], "po_number": r["po_number"], "ordered": r["ordered"], "deadline": r["deadline"],
                 "status": r["status"]})
    out = []
    for key, g in groups.items():
        if g["vendor_id"]:
            vdoc = await resolve_vendor_doc(db, g["vendor_id"])
            if vdoc:
                g["vendor_code"] = vdoc.get("garment_code") or vdoc.get("code") or ""
                g["vendor_name"] = vdoc.get("garment_name") or vdoc.get("name") or g["vendor_name"]
        mine = {r["po_id"] for r in g["po_rows"]}
        t = sum_lines([ln for ln in lines if ln["po_id"] in mine])
        staff_n = sum(1 for j in g["jobs"] if j["entry_source"] in ("staff", "mixed"))
        vend_n = sum(1 for j in g["jobs"] if j["entry_source"] in ("vendor", "mixed"))
        risks = [r["risk"] for r in g["po_rows"]]
        tested = t["accepted"] + t["reject"]
        out.append({
            "vendor_id": g["vendor_id"], "vendor_name": g["vendor_name"] or "(vendor belum diisi)",
            "vendor_code": g["vendor_code"], "po_count": len(g["po_rows"]), "job_count": len(g["jobs"]),
            **t, "progress_pct": progress_pct(t),
            "reject_rate": round(t["reject"] / tested * 100, 1) if tested else 0.0,
            "performance": "telat" if "telat" in risks else ("berisiko" if "berisiko" in risks else "aman"),
            "telat_count": risks.count("telat"),
            "entry_source": "mixed" if staff_n and vend_n else ("staff" if staff_n else ("vendor" if vend_n else "none")),
            "staff_qty": sum(j["staff_qty"] for j in g["jobs"]),
            "jobs": g["jobs"], "pending_pos": g["pending_pos"],
        })
    out.sort(key=lambda v: (-v["di_cmt"], -v["po_count"], v["vendor_name"]))
    return {"business_type": b, "count": len(out), "rows": out}


# ─── Laporan Selisih otomatis per baris PO ──────────────────────────────────
def _in_period(v, date_from: str, date_to: str) -> bool:
    if not date_from and not date_to:
        return True
    d = _to_date(v)
    if not d:
        return False
    if date_from and d.isoformat() < date_from:
        return False
    if date_to and d.isoformat() > date_to:
        return False
    return True


def cmt_done(r: dict, closed: bool = False) -> bool:
    """CMT sudah tidak memegang apa pun untuk baris ini (atau PO ditutup) — kekurangan baru berarti selisih."""
    return closed or (r["sent_cmt"] > 0 and r["di_cmt"] == 0 and r["in_qc"] == 0)


def line_differences(r: dict, closed: bool = False) -> List[Dict[str, Any]]:
    """Selisih di sepanjang rantai satu baris PO (fungsi murni).

    `qty` > 0 = lebih, < 0 = kurang. `kind`: 'lebih' | 'kurang' | 'tertunda' (masih menunggu tindakan:
    belum dikonfirmasi klien, reject belum selesai, klaim CMT belum sampai). Kekurangan terhadap pesanan baru
    dihitung setelah CMT selesai (tidak ada lagi di CMT / sedang QC) atau PO ditutup — selama masih berjalan,
    angka yang belum sampai bukan selisih."""
    bt = r["business_type"]
    done = cmt_done(r, closed)
    out = []

    def add(key, label, qty, kind=None, note=""):
        if qty:
            out.append({"key": key, "label": label, "qty": qty,
                        "kind": kind or ("lebih" if qty > 0 else "kurang"), "note": note})
    if r["sent_cmt"] > r["ordered"]:
        add("kirim_vs_pesan", "Potongan dikirim melebihi pesanan", r["sent_cmt"] - r["ordered"])
    elif closed and r["sent_cmt"] < r["ordered"]:
        add("kirim_vs_pesan", "Potongan dikirim kurang dari pesanan", r["sent_cmt"] - r["ordered"])
    if r["material_missing"]:
        add("bahan_kurang", "Bahan kurang saat diterima CMT", -r["material_missing"],
            note="; ".join(r.get("material_notes") or []))
    if r["material_received"] and r["produced"] and (done or r["produced"] > r["material_received"]):
        add("produksi_vs_bahan", "Diproduksi dibanding bahan diterima CMT", r["produced"] - r["material_received"])
    if r["produced"] and (done or r["produced"] > r["ordered"]):
        add("produksi_vs_pesan", "Diproduksi dibanding pesanan", r["produced"] - r["ordered"])
    if r["produced"] and r["arrived"] > r["produced"]:
        add("sampai_vs_produksi", "Sampai di DA melebihi yang diproduksi", r["arrived"] - r["produced"])
    if r["cmt_short_open"]:
        add("selisih_cmt", "Diklaim CMT tetapi belum sampai di DA", -r["cmt_short_open"], "tertunda")
    if r["scrap"]:
        add("dibuang", "Ditolak QC lalu dibuang (permak gagal)", -r["scrap"])
    if r["reject_open"]:
        add("reject_terbuka", "Ditolak QC, belum selesai", -r["reject_open"], "tertunda",
            "masih dipermak atau belum diputuskan")
    if bt == BT_MAKLON:
        if r["pending_confirm"]:
            add("belum_konfirmasi", "Dikirim, belum dikonfirmasi klien", -r["pending_confirm"], "tertunda",
                "belum dikonfirmasi")
        if r["buyer_short_open"]:
            add("selisih_klien", "Kurang diterima klien (selisih terbuka)", -r["buyer_short_open"], "tertunda")
    gap = r["final"] - r["ordered"]
    if r["accepted"] or r["dispatched"] or r["final"]:
        label = ("Masuk stok barang jadi" if bt == BT_INTERNAL else "Diterima klien") + " dibanding pesanan"
        if gap > 0:
            add("akhir_vs_pesan", label, gap)
        elif gap < 0 and done and not (bt == BT_MAKLON and r["pending_confirm"] + r["shippable"] > 0):
            add("akhir_vs_pesan", label, gap)
    return out


async def _reasons_by_item(db, pos: List[dict], item_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Alasan yang SUDAH tercatat untuk setiap baris: lebih qty, tutup kurang, selisih CMT/klien, laporan vendor."""
    from core.short_shipment import BUYER_RESOLUTIONS, BUYER_SHORT, CMT_RESOLUTIONS, CMT_SHORT
    from core.over_qty import STEP_LABELS
    out: Dict[str, List[Dict[str, Any]]] = {i: [] for i in item_ids}
    by_po_items: Dict[str, List[str]] = {}
    try:
        from routes.production_pos import CLOSE_SHORT_REASON_LABELS as close_labels
    except Exception:  # noqa: BLE001
        close_labels = {}
    items = await db.po_items.find({"id": {"$in": item_ids}}, {"_id": 0, "id": 1, "po_id": 1}).to_list(None) \
        if item_ids else []
    for it in items:
        by_po_items.setdefault(it.get("po_id"), []).append(it["id"])
    for po in pos:
        for ev in po.get("over_qty_events") or []:
            pid = ev.get("po_item_id")
            if pid in out:
                out[pid].append({"kind": "lebih_qty", "label": f"Lebih qty · {STEP_LABELS.get(ev.get('step'), ev.get('step_label') or '')}",
                                 "qty": _i(ev.get("over")), "reason": ev.get("reason") or "", "by": ev.get("by") or "",
                                 "at": str(ev.get("at") or "")[:10]})
        if po.get("status") == CLOSED_SHORT:
            label = close_labels.get(po.get("closed_reason"), po.get("closed_reason") or "")
            for pid in by_po_items.get(po["id"], []):
                short = next((_i(s.get("short")) for s in (po.get("short_lines_at_close") or [])
                              if s.get("po_item_id") == pid), None)
                out[pid].append({"kind": "tutup_kurang", "label": "PO ditutup kurang", "qty": short,
                                 "reason": " · ".join(x for x in (label, po.get("close_notes") or "") if x),
                                 "by": po.get("closed_by") or "", "at": str(po.get("closed_at") or "")[:10]})
    if item_ids:
        async for s in db[CMT_SHORT].find({"po_item_id": {"$in": item_ids}}, {"_id": 0}):
            if s.get("status") == "cancelled":
                continue
            res = CMT_RESOLUTIONS.get(s.get("resolution") or "", "")
            out[s["po_item_id"]].append({
                "kind": "selisih_cmt", "label": f"Selisih kirim CMT {s.get('short_number') or ''}".strip(),
                "qty": _i(s.get("qty_short")),
                "reason": " · ".join(x for x in ((res or "belum diputuskan"), s.get("resolution_notes") or "") if x),
                "by": s.get("resolved_by") or "", "at": str(s.get("resolved_at") or s.get("created_at") or "")[:10],
                "open": s.get("status") == "open"})
        async for s in db[BUYER_SHORT].find({"po_item_id": {"$in": item_ids}}, {"_id": 0}):
            if s.get("status") == "cancelled":
                continue
            res = BUYER_RESOLUTIONS.get(s.get("resolution") or "", "")
            out[s["po_item_id"]].append({
                "kind": "selisih_klien", "label": f"Kurang diterima klien {s.get('short_number') or ''}".strip(),
                "qty": _i(s.get("qty_short")),
                "reason": " · ".join(x for x in ((res or "belum diputuskan"), s.get("resolution_notes") or "") if x),
                "by": s.get("resolved_by") or "", "at": str(s.get("resolved_at") or s.get("created_at") or "")[:10],
                "open": s.get("status") == "open"})
        # keputusan permak atas barang yang ditolak QC (berhasil / dibuang) — alasan reject yang dibuang
        async for pm in db.dewi_cmt_permak.find({"po_item_id": {"$in": item_ids}}, {"_id": 0}):
            if (pm.get("source") or "reject") != "reject":
                continue
            fixed, scrap = _i(pm.get("qty_fixed")), _i(pm.get("qty_scrap"))
            done = pm.get("status") in ("selesai_berhasil", "gagal_buang")
            where = "dikembalikan ke CMT" if pm.get("permak_type") == "retur_ke_cmt" else "permak sendiri"
            out[pm["po_item_id"]].append({
                "kind": "permak",
                "label": f"Permak {pm.get('permak_number') or ''} · {where}".replace("  ", " "),
                "qty": _i(pm.get("qty")),
                "reason": (f"berhasil {fixed} · dibuang {scrap}" if done else "masih dikerjakan")
                + (f" · {pm.get('reason')}" if pm.get("reason") else ""),
                "by": pm.get("created_by") or "", "at": str(pm.get("updated_at") or pm.get("created_at") or "")[:10],
                "open": not done})
        # laporan vendor (production_variances) → baris PO lewat baris job
        ji_ids: Dict[str, str] = {}
        async for ji in db.production_job_items.find({"po_item_id": {"$in": item_ids}}, {"_id": 0, "id": 1, "po_item_id": 1}):
            ji_ids[ji["id"]] = ji["po_item_id"]
        po_ids = [p["id"] for p in pos]
        if po_ids:
            async for v in db.production_variances.find({"po_id": {"$in": po_ids}}, {"_id": 0}):
                for it in v.get("items") or []:
                    pid = ji_ids.get(it.get("job_item_id"))
                    if pid in out:
                        kind = "Lebih produksi" if v.get("variance_type") == "OVERPRODUCTION" else "Kurang produksi"
                        out[pid].append({"kind": "laporan_vendor", "label": f"Laporan vendor · {kind}",
                                         "qty": _i(it.get("variance_qty")), "reason": v.get("reason") or "",
                                         "by": v.get("reported_by") or "", "at": str(v.get("created_at") or "")[:10]})
    return out


async def selisih(db, bt: Optional[str], *, date_from: str = "", date_to: str = "", vendor_id: str = "",
                  po_id: str = "", only_diff: bool = False) -> Dict[str, Any]:
    """Laporan Selisih per baris PO: dipesan → bahan diterima CMT → diproduksi → masuk gudang / diterima klien."""
    b = norm_bt(bt) or BT_INTERNAL
    pos = await load_pos(db, b, vendor_id=vendor_id, po_ids=[po_id] if po_id else None)
    pos = [p for p in pos if _in_period(p.get("po_date") or p.get("created_at"), date_from, date_to)]
    lines = await po_lines(db, pos)
    reasons = await _reasons_by_item(db, pos, [ln["po_item_id"] for ln in lines])
    po_by_id = {p["id"]: p for p in pos}
    rows = []
    summary = {"lines": 0, "lines_diff": 0, "lebih": 0, "kurang": 0, "tertunda": 0, "belum_konfirmasi": 0,
               "tanpa_alasan": 0}
    for ln in lines:
        closed = po_closed(po_by_id.get(ln["po_id"]) or {})
        diffs = line_differences(ln, closed)
        rs = reasons.get(ln["po_item_id"]) or []
        has_diff = any(d["kind"] in ("lebih", "kurang") for d in diffs)
        final = next((d for d in diffs if d["key"] == "akhir_vs_pesan"), None)
        summary["lines"] += 1
        if has_diff:
            summary["lines_diff"] += 1
            if not rs:
                summary["tanpa_alasan"] += 1
        if final and final["qty"] > 0:
            summary["lebih"] += final["qty"]
        elif final and final["qty"] < 0:
            summary["kurang"] += -final["qty"]
        if any(d["kind"] == "tertunda" for d in diffs):
            summary["tertunda"] += 1
        if b == BT_MAKLON:
            summary["belum_konfirmasi"] += ln["pending_confirm"]
        if only_diff and not (has_diff or any(d["kind"] == "tertunda" for d in diffs)):
            continue
        rows.append({**ln, "final_gap": ln["final"] - ln["ordered"], "differences": diffs, "reasons": rs,
                     "has_diff": has_diff, "has_reason": bool(rs), "po_closed": closed,
                     "po_status": (po_by_id.get(ln["po_id"]) or {}).get("status") or ""})
    vendors = sorted({(p.get("vendor_id") or "", p.get("vendor_name") or "") for p in pos if p.get("vendor_id")},
                     key=lambda x: x[1])
    return {"business_type": b, "period": {"from": date_from or None, "to": date_to or None},
            "summary": summary, "count": len(rows), "rows": rows,
            "vendors": [{"id": v, "name": n} for v, n in vendors],
            "pos": [{"id": p["id"], "po_number": p.get("po_number") or "", "vendor_id": p.get("vendor_id") or ""}
                    for p in pos]}


async def vendor_reports(db, bt: Optional[str], *, date_from: str = "", date_to: str = "", vendor_id: str = "",
                         po_id: str = "") -> Dict[str, Any]:
    """Laporan selisih yang DIISI VENDOR (production_variances), disaring portal/periode/vendor/PO."""
    q: Dict[str, Any] = dict(bt_filter(bt))
    if vendor_id:
        q["vendor_id"] = vendor_id
    if po_id:
        q["po_id"] = po_id
    rows = await db.production_variances.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    rows = [r for r in rows if _in_period(r.get("created_at"), date_from, date_to)]
    from routes.exceptions import VARIANCE_STATUS_TRANSITIONS
    for r in rows:
        r["allowed_next"] = VARIANCE_STATUS_TRANSITIONS.get(r.get("status") or "Reported", [])
    over = [r for r in rows if r.get("variance_type") == "OVERPRODUCTION"]
    under = [r for r in rows if r.get("variance_type") == "UNDERPRODUCTION"]
    return {"count": len(rows), "rows": rows,
            "summary": {"over_count": len(over), "over_qty": sum(_i(r.get("total_variance_qty")) for r in over),
                        "under_count": len(under), "under_qty": sum(_i(r.get("total_variance_qty")) for r in under),
                        "open": sum(1 for r in rows if (r.get("status") or "Reported") != "Resolved")}}


async def buyer_receipt_rows(db, bt: Optional[str] = None, *, po_id: str = "", vendor_id: str = "",
                             date_from: str = "", date_to: str = "", extra_query: Optional[dict] = None) -> List[Dict[str, Any]]:
    """Kirim ke klien vs DITERIMA klien per PO (+ rincian per baris).

    Diterima = `qty_received` yang SUDAH dicatat. Baris yang belum dikonfirmasi klien TIDAK dianggap diterima
    penuh (dulu `qty_received` kosong = diterima semua): angkanya dipisah sebagai `total_unconfirmed` dan
    selisih hanya dihitung dari baris yang sudah dikonfirmasi. Deklarasi CMT→DA tidak ikut."""
    from core.dispatch_capacity import buyer_dispatch_items
    from core import short_shipment as shortmod
    pq: Dict[str, Any] = dict(bt_filter(bt))
    if po_id:
        pq["id"] = po_id
    if vendor_id:
        pq["vendor_id"] = vendor_id
    pos = await db.production_pos.find(pq, {"_id": 0, "id": 1, "po_number": 1, "customer_name": 1,
                                            "vendor_name": 1, "business_type": 1}).to_list(5000)
    po_meta = {p["id"]: p for p in pos}
    if not po_meta:
        return []
    items = await buyer_dispatch_items(db, po_ids=list(po_meta))
    ship_ids = list({it.get("shipment_id") for it in items if it.get("shipment_id")})
    ships: Dict[str, dict] = {}
    if ship_ids:
        sq: Dict[str, Any] = {"id": {"$in": ship_ids}, **(extra_query or {})}
        for s in await db.buyer_shipments.find(sq, {"_id": 0}).to_list(None):
            ships[s["id"]] = s
    rows: Dict[str, Dict[str, Any]] = {}
    for it in items:
        s = ships.get(it.get("shipment_id"))
        if s is None:
            continue
        pid = it.get("po_id") or s.get("po_id")
        meta = po_meta.get(pid)
        if not meta:
            continue
        if not _in_period(it.get("dispatch_date") or it.get("created_at"), date_from, date_to):
            continue
        row = rows.setdefault(pid, {
            "po_id": pid, "po_number": meta.get("po_number") or s.get("po_number") or "",
            "customer_name": meta.get("customer_name") or s.get("customer_name") or "",
            "vendor_name": s.get("vendor_name") or meta.get("vendor_name") or "",
            "business_type": bt_of(meta),
            "total_shipped": 0, "total_received": 0, "total_unconfirmed": 0, "total_variance": 0,
            "lines_unconfirmed": 0, "_items": {}})
        shipped = _i(it.get("qty_shipped"))
        confirmed = it.get("qty_received") is not None
        recv = min(shipped, _i(it.get("qty_received"))) if confirmed else 0
        key = it.get("po_item_id") or it.get("id")
        d = row["_items"].setdefault(key, {
            "po_item_id": it.get("po_item_id"), "sku": it.get("sku") or "", "product_name": it.get("product_name") or "",
            "serial_number": it.get("serial_number") or "", "size": it.get("size") or "", "color": it.get("color") or "",
            "shipped": 0, "received": 0, "unconfirmed": 0, "variance": 0})
        d["shipped"] += shipped
        row["total_shipped"] += shipped
        if confirmed:
            d["received"] += recv
            d["variance"] += shipped - recv
            row["total_received"] += recv
            row["total_variance"] += shipped - recv
        else:
            d["unconfirmed"] += shipped
            row["total_unconfirmed"] += shipped
            if shipped:
                row["lines_unconfirmed"] += 1
    short_map = await shortmod.buyer_short_totals(db, po_ids=list(rows)) if rows else {}
    out = []
    for pid, row in rows.items():
        row["items"] = list(row.pop("_items").values())
        sm = short_map.get(pid, {})
        row["qty_short_open"] = _i(sm.get("qty_short_open"))
        row["qty_short_resolved"] = _i(sm.get("qty_short_resolved"))
        row["short_docs"] = sm.get("items") or []
        row["total_variance_effective"] = row["total_variance"] + row["qty_short_open"]
        row["status"] = "belum_dikonfirmasi" if row["total_unconfirmed"] else (
            "selisih" if row["total_variance_effective"] else "sesuai")
        for it in row["items"]:
            it["qty_short_open"] = sum(_i(x.get("qty_open")) for x in (sm.get("items") or [])
                                       if x.get("po_item_id") == it.get("po_item_id") and x.get("status") == "open")
        out.append(row)
    out.sort(key=lambda r: r.get("po_number") or "")
    return out


# ─── Kapasitas CMT (beban internal + maklon vs kapasitas, laju setor) ────────
async def capacity(db, bt: Optional[str] = None, *, window_days: int = 30,
                   today: Optional[date] = None) -> Dict[str, Any]:
    """Beban di CMT dari SEMUA PO berjalan (internal + maklon: satu CMT mengerjakan keduanya) vs
    `vendor_partners.capacity_pcs`, ditambah laju setor nyata (pcs lolos QC per hari, N hari terakhir) dan
    perkiraan hari untuk menghabiskan beban. Pengganti Kapasitas di Analitik Produksi (data mesin/lini lama
    yang sudah mati) — keputusan 11."""
    from core.cmt_receipt_status import is_done
    from utils.waktu import today_wib
    today = today or today_wib()
    pos = await load_pos(db, None, running=True)
    lines = await po_lines(db, pos)
    po_rows = rollup_pos(pos, lines, today)
    load: Dict[str, Dict[str, Any]] = {}
    for r in po_rows:
        vid = r["vendor_id"]
        if not vid:
            continue
        v = load.setdefault(vid, {"internal": 0, "maklon": 0, "sent": 0, "po_count": 0, "telat_po": 0,
                                  "po_internal": 0, "po_maklon": 0})
        v[r["business_type"]] += r["di_cmt"]
        v["po_" + r["business_type"]] += 1
        v["sent"] += r["sent_cmt"]
        v["po_count"] += 1
        if r["risk"] == "telat":
            v["telat_po"] += 1
    since = today - timedelta(days=window_days)
    rate: Dict[str, int] = {}
    recs = await db.cmt_receipts.find({}, {"_id": 0, "id": 1, "status": 1, "cmt_vendor_id": 1, "po_id": 1,
                                           "qc_completed_at": 1, "approved_at": 1, "receipt_date": 1}).to_list(20000)
    po_vendor = {p["id"]: p.get("vendor_id") for p in await db.production_pos.find(
        {}, {"_id": 0, "id": 1, "vendor_id": 1}).to_list(10000)}
    rec_vendor: Dict[str, str] = {}
    for rc in recs:
        d = _to_date(rc.get("qc_completed_at") or rc.get("approved_at") or rc.get("receipt_date"))
        if is_done(rc.get("status")) and d and d >= since:
            rec_vendor[rc["id"]] = rc.get("cmt_vendor_id") or po_vendor.get(rc.get("po_id")) or ""
    if rec_vendor:
        async for ln in db.cmt_receipt_lines.find({"receipt_id": {"$in": list(rec_vendor)}},
                                                  {"_id": 0, "receipt_id": 1, "qty_actual": 1}):
            vid = rec_vendor.get(ln.get("receipt_id"))
            if vid:
                rate[vid] = rate.get(vid, 0) + _i(ln.get("qty_actual"))
    partners = await db.vendor_partners.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    vendors = []
    tot = {"capacity_pcs": 0, "load_pcs": 0, "load_internal_pcs": 0, "load_maklon_pcs": 0, "daily_rate": 0.0}
    for p in partners:
        vid = p.get("id")
        ld = load.get(vid, {})
        cap = _i(p.get("capacity_pcs"))
        li, lm = _i(ld.get("internal")), _i(ld.get("maklon"))
        total_load = li + lm
        daily = round(rate.get(vid, 0) / window_days, 1)
        util = round(total_load / cap * 100, 1) if cap > 0 else None
        status = ("no_capacity" if cap <= 0 else "over" if total_load > cap
                  else "near" if util is not None and util >= 85 else "ok")
        if not p.get("is_active", True) and not total_load:
            continue
        tot["capacity_pcs"] += cap
        tot["load_pcs"] += total_load
        tot["load_internal_pcs"] += li
        tot["load_maklon_pcs"] += lm
        tot["daily_rate"] += daily
        vendors.append({
            "vendor_id": vid, "name": p.get("name") or "", "code": p.get("code") or "",
            "is_active": p.get("is_active", True), "capacity_pcs": cap, "capacity_note": p.get("capacity_note") or "",
            "load_internal_pcs": li, "load_maklon_pcs": lm, "current_load_pcs": total_load,
            "po_internal": _i(ld.get("po_internal")), "po_maklon": _i(ld.get("po_maklon")),
            "active_po_count": _i(ld.get("po_count")), "telat_po_count": _i(ld.get("telat_po")),
            "sent_pcs": _i(ld.get("sent")),
            "available_pcs": (cap - total_load) if cap > 0 else None, "utilization_pct": util, "status": status,
            "accepted_window": rate.get(vid, 0), "daily_rate": daily,
            "days_to_clear": (int(-(-total_load // daily)) if daily > 0 else None) if total_load else 0,
        })
    order = {"over": 0, "near": 1, "ok": 2, "no_capacity": 3}
    vendors.sort(key=lambda v: (order.get(v["status"], 9), -(v["current_load_pcs"] or 0)))
    tot["daily_rate"] = round(tot["daily_rate"], 1)
    tot["available_pcs"] = tot["capacity_pcs"] - tot["load_pcs"]
    tot["utilization_pct"] = round(tot["load_pcs"] / tot["capacity_pcs"] * 100, 1) if tot["capacity_pcs"] else None
    tot["over_count"] = sum(1 for v in vendors if v["status"] == "over")
    tot["no_capacity_count"] = sum(1 for v in vendors if v["status"] == "no_capacity")
    return {"business_type": norm_bt(bt) or "", "window_days": window_days, "vendor_count": len(vendors),
            "totals": tot, "vendors": vendors}


def check_new_order(cap: Dict[str, Any], qty: int, target_days: int, vendor_id: str = "") -> Dict[str, Any]:
    """Cek order baru muat atau tidak (fungsi murni) — pengganti 'cek WO' kapasitas pabrik lama.

    Laju = rata-rata pcs lolos QC per hari dari CMT (nyata, bukan setelan). Hari dibutuhkan =
    (beban yang sudah ada + order baru) ÷ laju. Kapasitas pcs vendor dipakai sebagai batas barang
    yang bisa dipegang sekaligus."""
    vs = [v for v in cap.get("vendors") or [] if not vendor_id or v["vendor_id"] == vendor_id]
    load = sum(v["current_load_pcs"] for v in vs)
    room = sum(max(0, v["available_pcs"] or 0) for v in vs if v["capacity_pcs"] > 0)
    rate = sum(v["daily_rate"] for v in vs)
    qty = max(0, _i(qty))
    days_needed = int(-(-(load + qty) // rate)) if rate > 0 else None
    warnings = []
    if rate <= 0:
        warnings.append("Belum ada setoran lolos QC dalam periode ini, jadi lama pengerjaan belum bisa diperkirakan.")
    if room < qty:
        warnings.append(f"Sisa kapasitas {room} pcs lebih kecil dari order {qty} pcs.")
    if days_needed is not None and target_days and days_needed > target_days:
        warnings.append(f"Perkiraan selesai {days_needed} hari, melebihi target {target_days} hari.")
    feasible = bool(rate > 0 and room >= qty and (days_needed or 0) <= (target_days or 10 ** 6))
    return {"qty": qty, "target_days": target_days, "vendor_id": vendor_id or None, "current_load": load,
            "room_pcs": room, "daily_rate": round(rate, 1), "days_needed": days_needed, "feasible": feasible,
            "warnings": warnings}
