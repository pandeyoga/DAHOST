"""core.sewing_rate — upah jahit per pcs SPK/PO (keputusan owner K12, 7 Nov 2026).

Upah jahit diisi per baris PO LANGSUNG di form PO, untuk PO internal maupun maklon, dan boleh berbeda per
penjahit (CMT). Satu sumber angka: `po_items.cmt_price_snapshot` — dibaca tagihan CMT
(`production_maklon_bridge`), lapisan HPP FG (`core.fg_cost_layers`), Monitoring CMT, dan rekap Biaya Jahit.

Pintu bersama (dipakai form PO, menu Biaya Jahit, dan Kirim Material CMT):
  parse_rate(v, label)        angka ≥ 0 dari isian (kosong = 0); negatif / bukan angka → ValueError
  rate_lock(db, po_id)        tagihan CMT aktif yang mengunci tarif PO itu (None = masih boleh diubah)
  suggest_rates(db, lines, …) usulan tarif + asal angkanya per baris
  missing_rate_lines(items)   label baris tanpa upah jahit
"""
from __future__ import annotations

from datetime import datetime, timezone

# Tagihan CMT berstatus ini tidak mengunci tarif (dibatalkan).
CMT_BILL_VOID_STATUSES = ("cancelled", "void", "voided", "rejected", "batal")
# PO batal tidak dipakai sebagai riwayat tarif (sama dengan product_costing.CANCELLED_PO_STATUSES).
_CANCELLED_PO = {"cancelled", "rejected", "void", "dibatalkan"}
# Baris riwayat yang dibaca untuk usulan (terbaru dulu) — cukup untuk ratusan model.
HISTORY_SCAN_ROWS = 2000

SOURCE_LABELS = {
    "vendor_last": "tarif terakhir penjahit ini",
    "model_default": "tarif bawaan model",
    "catalog_default": "tarif bawaan katalog buyer",
    "last_any": "tarif terakhir model ini",
    "none": "belum ada tarif",
}


def _f(v, d: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(d)
        return float(v)
    except (TypeError, ValueError):
        return float(d)


def _rp(v) -> str:
    return "Rp " + f"{round(_f(v)):,.0f}".replace(",", ".")


def parse_rate(value, label: str = "baris") -> float:
    """Upah jahit per pcs dari isian form/API. Kosong = 0. Negatif atau bukan angka → ValueError."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        v = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Upah jahit per pcs untuk {label} bukan angka ('{value}').") from None
    if v != v or v < 0:      # NaN atau negatif
        raise ValueError(f"Upah jahit per pcs untuk {label} tidak boleh negatif.")
    return round(v, 2)


def line_label(it: dict) -> str:
    return " ".join(x for x in (it.get("sku") or it.get("product_name") or "baris", it.get("size") or "")
                    if x).strip()


def rate_changed(old, new) -> bool:
    return abs(_f(old) - _f(new)) > 0.004


async def rate_lock(db, po_id: str) -> dict | None:
    """Tagihan CMT aktif pertama untuk PO ini (None = tarif masih boleh diubah).

    2026-11-06 (Tahap 2): tarif jahit boleh diubah SAMPAI tagihan CMT (`dewi_cmt_payments`) PO itu terbentuk;
    sesudahnya dikunci — tagihan, lapisan HPP FG, dan HPP per potong membaca angka yang sama."""
    if not po_id:
        return None
    bill = await db.dewi_cmt_payments.find_one(
        {"po_id": po_id, "status": {"$nin": list(CMT_BILL_VOID_STATUSES)}},
        {"_id": 0, "id": 1, "payment_code": 1, "payment_number": 1, "invoice_number": 1, "status": 1})
    if not bill:
        return None
    # `payment_code` = nomor yang ditulis mesin tagihan CMT (PAY-CMT-…); dua nama lain untuk data lama.
    ref = bill.get("payment_code") or bill.get("payment_number") or bill.get("invoice_number") or bill.get("id")
    return {"bill_id": bill.get("id"), "bill_ref": ref, "status": bill.get("status"),
            "message": (f"Upah jahit PO ini terkunci karena tagihan CMT {ref} sudah dibuat. "
                        "Ubah lewat koreksi tagihan CMT di Keuangan.")}


def missing_rate_lines(items) -> list:
    """Label baris ber-qty yang upah jahitnya masih 0/kosong."""
    return [line_label(it) for it in items or []
            if int(_f(it.get("qty"))) > 0 and _f(it.get("cmt_price_snapshot")) <= 0]


def _model_key(line: dict, business_type: str):
    """Kunci "model yang sama": artikel katalog (maklon) / model master (internal); cadangan SKU."""
    if business_type == "maklon" and line.get("catalog_item_id"):
        return ("catalog_item_id", line["catalog_item_id"])
    if line.get("model_id"):
        return ("model_id", line["model_id"])
    if line.get("catalog_item_id"):
        return ("catalog_item_id", line["catalog_item_id"])
    if line.get("sku"):
        return ("sku", line["sku"])
    return None


def _when(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


async def suggest_rates(db, lines: list, *, vendor_id: str | None = None, business_type: str = "internal",
                        exclude_po_id: str | None = None) -> dict:
    """Usulan upah jahit per baris → {key: {rate, source, note, po_number, vendor_name}}.

    `lines` = [{key, model_id?, catalog_item_id?, sku?}]. Urutan usulan (keputusan K12):
      1. tarif terakhir untuk model yang sama DENGAN penjahit yang sama (riwayat `po_items` PO lain);
      2. tarif bawaan model (dikunci pemilik di Kalkulator HPP) / tarif bawaan artikel katalog buyer;
      3. bila penjahit belum dipilih: tarif terakhir model itu dengan penjahit mana pun;
      4. kosong.
    PO batal, PO jenis lain (internal ≠ maklon), dan PO yang sedang diubah tidak dipakai."""
    business_type = "maklon" if business_type == "maklon" else "internal"
    keyed = []
    for ln in lines or []:
        mk = _model_key(ln or {}, business_type)
        keyed.append((ln or {}, mk))
    by_field: dict = {}
    for _ln, mk in keyed:
        if mk:
            by_field.setdefault(mk[0], set()).add(mk[1])

    rows = []
    if by_field:
        ors = [{f: {"$in": sorted(v)}} for f, v in by_field.items()]
        rows = await db.po_items.find(
            {"cmt_price_snapshot": {"$gt": 0}, "$or": ors},
            {"_id": 0, "po_id": 1, "model_id": 1, "catalog_item_id": 1, "sku": 1, "cmt_price_snapshot": 1,
             "created_at": 1}).sort("created_at", -1).to_list(HISTORY_SCAN_ROWS)
    po_ids = sorted({r.get("po_id") for r in rows if r.get("po_id")})
    pos = {}
    if po_ids:
        async for p in db.production_pos.find(
                {"id": {"$in": po_ids}},
                {"_id": 0, "id": 1, "po_number": 1, "vendor_id": 1, "vendor_name": 1, "status": 1,
                 "business_type": 1, "created_at": 1}):
            pos[p["id"]] = p
    hist = []
    for r in rows:
        p = pos.get(r.get("po_id"))
        if not p or r.get("po_id") == exclude_po_id:
            continue
        if str(p.get("status") or "").strip().lower() in _CANCELLED_PO:
            continue
        if (p.get("business_type") or "internal") != business_type:
            continue
        hist.append((r, p))
    hist.sort(key=lambda rp: _when(rp[0].get("created_at")), reverse=True)

    model_ids = sorted({mk[1] for _ln, mk in keyed if mk and mk[0] == "model_id"})
    cat_ids = sorted({mk[1] for _ln, mk in keyed if mk and mk[0] == "catalog_item_id"})
    model_default = {}
    if model_ids:
        from core.product_costing import OVERRIDE_COLL
        async for o in db[OVERRIDE_COLL].find({"model_id": {"$in": model_ids}},
                                              {"_id": 0, "model_id": 1, "cmt_rate_per_pcs": 1}):
            if _f(o.get("cmt_rate_per_pcs")) > 0:
                model_default[o["model_id"]] = _f(o.get("cmt_rate_per_pcs"))
    catalog_default = {}
    if cat_ids:
        async for c in db.dewi_maklon_buyer_catalog.find(
                {"id": {"$in": cat_ids}}, {"_id": 0, "id": 1, "artikel_code": 1, "default_cmt_price": 1}):
            if _f(c.get("default_cmt_price")) > 0:
                catalog_default[c["id"]] = (_f(c.get("default_cmt_price")), c.get("artikel_code") or "")
    vendor_name = ""
    if vendor_id:
        vendor_name = next((p.get("vendor_name") for _r, p in hist if p.get("vendor_id") == vendor_id
                            and p.get("vendor_name")), "")
        if not vendor_name:     # master vendor yang sama dengan routes.production_rbac.resolve_vendor_doc
            vd = (await db.garments.find_one({"id": vendor_id}, {"_id": 0, "garment_name": 1})
                  or await db.vendor_partners.find_one({"id": vendor_id}, {"_id": 0, "name": 1}) or {})
            vendor_name = vd.get("garment_name") or vd.get("name") or ""

    def _pick(ln, mk, pred):
        """Baris riwayat terbaru untuk model ini yang lolos `pred`; SKU yang sama didahulukan."""
        same = [(r, p) for r, p in hist if mk and r.get(mk[0]) == mk[1] and pred(p)]
        if not same:
            return None
        if ln.get("sku"):
            exact = next(((r, p) for r, p in same if r.get("sku") == ln["sku"]), None)
            if exact:
                return exact
        return same[0]

    out: dict = {}
    for idx, (ln, mk) in enumerate(keyed):
        key = str(ln.get("key") if ln.get("key") not in (None, "") else idx)
        res = {"rate": 0.0, "source": "none", "note": "Belum ada riwayat tarif — isi manual.",
               "po_number": "", "vendor_name": ""}
        hit = _pick(ln, mk, lambda p: p.get("vendor_id") == vendor_id) if vendor_id else None
        if hit:
            r, p = hit
            res.update(rate=round(_f(r.get("cmt_price_snapshot")), 2), source="vendor_last",
                       po_number=p.get("po_number") or "", vendor_name=p.get("vendor_name") or vendor_name,
                       note=f"Tarif terakhir {p.get('vendor_name') or vendor_name or 'penjahit ini'} · "
                            f"{p.get('po_number') or '-'}")
        elif mk and mk[0] == "model_id" and mk[1] in model_default:
            res.update(rate=round(model_default[mk[1]], 2), source="model_default",
                       note="Tarif bawaan model (Kalkulator HPP)"
                            + (f" — belum ada riwayat dengan {vendor_name}" if vendor_name else ""))
        elif mk and mk[0] == "catalog_item_id" and mk[1] in catalog_default:
            rate, art = catalog_default[mk[1]]
            res.update(rate=round(rate, 2), source="catalog_default",
                       note=f"Tarif bawaan katalog buyer{(' ' + art) if art else ''}"
                            + (f" — belum ada riwayat dengan {vendor_name}" if vendor_name else ""))
        elif not vendor_id:
            hit = _pick(ln, mk, lambda p: True)
            if hit:
                r, p = hit
                res.update(rate=round(_f(r.get("cmt_price_snapshot")), 2), source="last_any",
                           po_number=p.get("po_number") or "", vendor_name=p.get("vendor_name") or "",
                           note=f"Tarif terakhir model ini ({p.get('vendor_name') or 'tanpa penjahit'}) · "
                                f"{p.get('po_number') or '-'} — penjahit belum dipilih")
        elif vendor_name:
            res["note"] = f"Belum ada riwayat tarif dengan {vendor_name} — isi manual."
        out[key] = res
    return out


def suggestion_text(s: dict) -> str:
    """Kalimat pendek usulan untuk pesan/log: 'Rp 9.000 (tarif terakhir CMT X · PO-…)'."""
    if not s or _f(s.get("rate")) <= 0:
        return (s or {}).get("note") or "Belum ada riwayat tarif."
    return f"{_rp(s.get('rate'))} ({s.get('note')})"
