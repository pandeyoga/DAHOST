"""core.purchase_returns — Retur Pembelian (RTP) & Nota Debit (ND). 2026-11-02, keputusan owner K11.

LATAR (audit g.md No.20–22)
---------------------------
* Satu-satunya "retur supplier" dulu = aksi karantina tanpa pemasok, tanpa nota, tanpa cara
  penyelesaian; barang bernilai yang diretur dijurnal sebagai BEBAN (Dr 6-2400 / Cr 1-1401),
  hutang tetap penuh ⇒ DA berisiko membayar penuh (uji T1: 330.000 beban palsu).
* Lepas reject GR dijurnal Dr persediaan / Cr beban, tanpa GRNI/AP; tagihan dari GR tidak bisa
  menagih qty yang dilepas.

KEPUTUSAN OWNER (K11)
---------------------
* Dokumen "Retur Pembelian" dimiliki Pengadaan; Nota Debit diterbitkan Keuangan.
* Penyelesaian: tukar barang / potong tagihan (nota debit) / refund / diterima dengan diskon /
  dimusnahkan. DA bukan PKP → TANPA PPN retur.
* Harga dasar = harga GR asal; selisih vs HPP rata-rata (WAC) → 5-1900 PPV.
* Lepas reject = penerimaan susulan pada GR yang sama (Dr persediaan / Cr GRNI) dengan harga
  potongan yang diketik Keuangan (bawaan harga PO); tagihan dari GR boleh menagih qty susulan.

MODEL (Q = qty, H = harga GR, W = HPP rata-rata saat kirim, Hd = harga diskon)
------------------------------------------------------------------------------
Bagian "belum bernilai" (reject GR di karantina — kasus A) belum pernah masuk GL maupun tagihan;
bagian "bernilai" (stok / karantina bernilai — kasus B) ada di GL senilai W.

| Penyelesaian         | Kirim / proses                         | Penyelesaian                                   |
|----------------------|----------------------------------------|------------------------------------------------|
| tukar / ND / refund  | B: Dr klaim Q×H / Cr persediaan Q×W ± PPV | tukar: B Dr persediaan / Cr klaim; A = penerimaan susulan (Dr persediaan / Cr GRNI, bisa ditagih) |
|                      | A: tanpa jurnal                        | ND: B Dr GRNI (belum ditagih) atau Hutang (sudah) / Cr klaim; A: dokumen saja |
|                      |                                        | refund (hanya B): Dr kas/bank / Cr klaim       |
| musnah, pemasok tanggung | sama dengan kirim                  | ND (sama dengan baris ND)                      |
| musnah, DA tanggung  | B: Dr beban musnah / Cr persediaan Q×W; A: Dr beban musnah / Cr GRNI Q×H (bisa ditagih) | langsung selesai |
| diterima dg diskon   | —                                      | ND: A = penerimaan susulan @Hd; B: Dr GRNI/Hutang Q×(H−Hd) / Cr persediaan (HPP turun) atau PPV bila stok habis |

Modul ini berisi fungsi MURNI (perencana jurnal & hitung tagihan GR) + penerimaan susulan (DB).
Endpoint ada di `routes/rahaza_purchase_returns.py`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

RTP_COLL = "rahaza_purchase_returns"
DN_COLL = "rahaza_debit_notes"

SETTLEMENTS = {
    "exchange": "Tukar barang",
    "debit_note": "Potong tagihan (nota debit)",
    "refund": "Refund uang",
    "accept_discount": "Diterima dengan diskon",
    "destroy": "Dimusnahkan",
}
BORNE_BY = ("supplier", "da")
STATUS_LABELS = {"draft": "Draft", "awaiting_settlement": "Menunggu Penyelesaian",
                 "settled": "Selesai", "cancelled": "Batal"}
# Penyelesaian yang barangnya keluar gudang lewat "Kirim / Proses"
SHIPPING_SETTLEMENTS = ("exchange", "debit_note", "refund", "destroy")
# Penyelesaian yang ditutup Keuangan dengan Nota Debit
DEBIT_NOTE_SETTLEMENTS = ("debit_note", "accept_discount", "destroy")


def _now():
    return datetime.now(timezone.utc)


def _uid():
    return str(uuid.uuid4())


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v), 2)


def _r4(v) -> float:
    return round(_f(v), 4)


# ═════════════════════════════════════════════════════════════════════════════
# 1. HARGA & TAGIHAN BARIS GR (murni)
# ═════════════════════════════════════════════════════════════════════════════
def gr_line_price(item: dict) -> float:
    """Harga satuan baris GR (satuan dasar) — SATU definisi untuk jurnal GR (GRNI), HPP rata-rata,
    tagihan dari GR, lepas reject, dan Retur Pembelian. Dulu GR memakai `unit_price` lebih dulu
    sementara tagihan dari GR memakai `unit_cost` lebih dulu."""
    for k in ("unit_price", "unit_cost"):
        v = _f((item or {}).get(k))
        if v > 0:
            return v
    return 0.0


def line_id_of(li: dict) -> str:
    return li.get("id") or li.get("po_item_id") or ""


def base_billed(gr: dict, li: dict) -> bool:
    """Qty bersih baris GR sudah masuk faktur? Faktur baru menandai per baris (`base_ap_invoice_id`);
    GR lama hanya punya `ap_invoice_id` di dokumen = seluruh baris sudah ditagih."""
    if "base_ap_invoice_id" in (li or {}):
        return bool(li.get("base_ap_invoice_id"))
    return bool((gr or {}).get("ap_invoice_id"))


def line_values(li: dict) -> dict:
    """Ringkasan nilai satu baris GR (murni): bersih, susulan, potongan sebelum faktur."""
    price = gr_line_price(li)
    net = max(0.0, _f(li.get("received_qty")) - _f(li.get("rejected_qty")))
    late = [lr for lr in (li.get("late_receipts") or []) if isinstance(lr, dict)]
    ded = [d for d in (li.get("billing_deductions") or []) if isinstance(d, dict)]
    late_q = sum(_f(x.get("qty")) for x in late)
    late_v = sum(_f(x.get("amount")) for x in late)
    ded_q = sum(_f(x.get("qty")) for x in ded)
    ded_v = sum(_f(x.get("amount")) for x in ded)
    return {"price": price, "net_qty": _r4(net), "late_qty": _r4(late_q), "late_value": _r2(late_v),
            "deducted_qty": _r4(ded_q), "deducted_value": _r2(ded_v),
            "received_qty_total": _r4(net + late_q),
            "received_value": _r2(net * price + late_v - ded_v)}


def gr_billable_lines(gr: dict) -> list:
    """Baris yang BELUM ditagih dari satu GR (murni) — dasar Tagihan dari GR & 3-way match.

    * baris dasar = qty bersih − qty yang diselesaikan nota debit sebelum faktur, nilai bersih −
      potongan (nota debit / diskon) — hanya bila qty bersih baris itu belum masuk faktur;
    * tiap penerimaan susulan (lepas reject, pengganti tukar barang, musnah ditanggung DA) yang
      belum masuk faktur = baris tersendiri pada harganya sendiri.
    * 2026-11-06 (Tahap 1): tagihan SEBAGIAN dicatat per baris (`base_billed_qty`/`base_billed_value`,
      atau `billed_qty`/`billed_value` pada penerimaan susulan) — sisanya tetap bisa ditagih. Penanda
      `base_ap_invoice_id` / `ap_invoice_id` baru diisi bila baris itu sudah tertagih penuh.
    """
    out = []
    for li in (gr or {}).get("items") or []:
        lid = line_id_of(li)
        v = line_values(li)
        if not base_billed(gr, li):
            q = _r4(v["net_qty"] - v["deducted_qty"] - _f(li.get("base_billed_qty")))
            amt = _r2(v["net_qty"] * v["price"] - v["deducted_value"] - _f(li.get("base_billed_value")))
            if q > 1e-9 or amt > 0.005:
                out.append({"key": lid, "gr_item_id": lid, "type": "base", "qty": max(q, 0.0),
                            "price": round(amt / q, 4) if q > 1e-9 else v["price"], "amount": amt,
                            "gr_price": v["price"]})
        for lr in li.get("late_receipts") or []:
            if not isinstance(lr, dict) or lr.get("ap_invoice_id"):
                continue
            q = _r4(_f(lr.get("qty")) - _f(lr.get("billed_qty")))
            amt = _r2(_f(lr.get("amount")) - _f(lr.get("billed_value")))
            if q <= 1e-9 and amt <= 0.005:
                continue
            out.append({"key": f"{lid}:late:{lr.get('id')}", "gr_item_id": lid, "type": "late",
                        "late_id": lr.get("id"), "qty": max(q, 0.0), "price": _f(lr.get("unit_price")),
                        "amount": amt, "gr_price": _f(lr.get("unit_price")),
                        "source": lr.get("source")})
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 2. PERENCANA JURNAL (murni) — baris ber-PERAN untuk rahaza_posting.post_purchase_return
# ═════════════════════════════════════════════════════════════════════════════
def _ln(role, debit=0.0, credit=0.0, kind=None, desc=""):
    d = {"role": role, "debit": _r2(debit), "credit": _r2(credit), "description": desc}
    if kind:
        d["kind"] = kind
    return d


def claim_lines(qty: float, gr_price: float, wac: float, kind: str, desc: str = "") -> list:
    """Barang bernilai keluar ke pemasok: Dr klaim Q×H / Cr persediaan Q×W, selisih → PPV."""
    v, c = _r2(_f(qty) * _f(gr_price)), _r2(_f(qty) * _f(wac))
    if v <= 0 and c <= 0:
        return []
    lines = [_ln("supplier_claim", debit=v, desc=desc), _ln("inventory", credit=c, kind=kind, desc=desc)]
    diff = _r2(c - v)
    if diff > 0:
        lines.append(_ln("price_variance", debit=diff, desc=desc))
    elif diff < 0:
        lines.append(_ln("price_variance", credit=-diff, desc=desc))
    return lines


def plan_send(*, settlement: str, borne_by: str | None, valued_qty: float, unvalued_qty: float,
              gr_price: float, wac: float, kind: str, desc: str = "") -> dict:
    """Jurnal & akibat saat barang retur KELUAR gudang (kirim ke pemasok / dimusnahkan).

    Return {lines, claim_amount, late_billable: {qty, unit_price}|None, settles: bool}."""
    if settlement not in SHIPPING_SETTLEMENTS:
        raise ValueError(f"penyelesaian '{settlement}' tidak melalui kirim/proses")
    vq, uq = max(0.0, _f(valued_qty)), max(0.0, _f(unvalued_qty))
    if settlement == "destroy" and borne_by == "da":
        lines = []
        if vq > 0:
            amt = _r2(vq * _f(wac))
            lines += [_ln("scrap_expense", debit=amt, desc=desc), _ln("inventory", credit=amt, kind=kind, desc=desc)]
        late = None
        if uq > 0:
            amt = _r2(uq * _f(gr_price))
            lines += [_ln("scrap_expense", debit=amt, desc=desc), _ln("grni", credit=amt, desc=desc)]
            late = {"qty": _r4(uq), "unit_price": _f(gr_price)}
        return {"lines": lines, "claim_amount": 0.0, "late_billable": late, "settles": True}
    return {"lines": claim_lines(vq, gr_price, wac, kind, desc) if vq > 0 else [],
            "claim_amount": _r2(vq * _f(gr_price)), "late_billable": None, "settles": False}


def plan_replacement_valued(valued_qty: float, gr_price: float, kind: str, desc: str = "") -> list:
    """Pengganti untuk bagian bernilai datang: Dr persediaan / Cr klaim Q×H (bagian belum bernilai
    = penerimaan susulan biasa, lihat `receive_late`)."""
    amt = _r2(_f(valued_qty) * _f(gr_price))
    if amt <= 0:
        return []
    return [_ln("inventory", debit=amt, kind=kind, desc=desc), _ln("supplier_claim", credit=amt, desc=desc)]


def plan_debit_note(claim_amount: float, *, billed: bool, desc: str = "") -> list:
    """Nota debit atas klaim barang bernilai: Dr Hutang (faktur sudah ada) / GRNI (belum) / Cr klaim."""
    amt = _r2(claim_amount)
    if amt <= 0:
        return []
    return [_ln("ap" if billed else "grni", debit=amt, desc=desc), _ln("supplier_claim", credit=amt, desc=desc)]


def plan_discount_valued(valued_qty: float, gr_price: float, disc_price: float, *, billed: bool,
                         absorbed: bool, kind: str, desc: str = "") -> list:
    """Diterima dengan diskon, barang bernilai: potongan Q×(H−Hd) → Dr Hutang/GRNI / Cr persediaan
    (HPP turun) atau Cr PPV bila stok bernilai sudah habis (`absorbed=False`)."""
    cut = _r2(_f(valued_qty) * (_f(gr_price) - _f(disc_price)))
    if cut <= 0:
        return []
    cr = _ln("inventory", credit=cut, kind=kind, desc=desc) if absorbed else _ln("price_variance", credit=cut, desc=desc)
    return [_ln("ap" if billed else "grni", debit=cut, desc=desc), cr]


def plan_refund(claim_amount: float, desc: str = "") -> list:
    """Uang refund diterima: Dr kas/bank / Cr klaim."""
    amt = _r2(claim_amount)
    if amt <= 0:
        return []
    return [_ln("cash", debit=amt, desc=desc), _ln("supplier_claim", credit=amt, desc=desc)]


# ═════════════════════════════════════════════════════════════════════════════
# 3. PENERIMAAN SUSULAN PADA GR (DB) — lepas reject & pengganti bagian reject GR
# ═════════════════════════════════════════════════════════════════════════════
async def record_late_receipt(db, *, gr_id: str, line_id: str, qty: float, unit_price: float,
                              source: str, ref_id: str = "", ref_number: str = "",
                              je_number: str | None = None, actor: dict | None = None) -> dict:
    """Catat qty susulan (bisa ditagih) di baris GR asal. Return entri yang dicatat."""
    gr = await db.warehouse_receiving.find_one({"id": gr_id}, {"_id": 0})
    if not gr:
        raise ValueError("GR asal tidak ditemukan")
    entry = {"id": _uid(), "qty": _r4(qty), "unit_price": _f(unit_price), "amount": _r2(_f(qty) * _f(unit_price)),
             "source": source, "ref_id": ref_id, "ref_number": ref_number, "je_number": je_number,
             "ap_invoice_id": None, "at": _now(), "by": (actor or {}).get("name", "")}
    items = gr.get("items") or []
    hit = False
    for li in items:
        if line_id_of(li) == line_id:
            li.setdefault("late_receipts", []).append(entry)
            li["late_received_qty"] = _r4(_f(li.get("late_received_qty")) + _f(qty))
            hit = True
            break
    if not hit:
        raise ValueError("baris GR asal tidak ditemukan")
    # `has_unbilled_lines` membuat GR yang sudah pernah difaktur muncul lagi di "siap ditagih"
    await db.warehouse_receiving.update_one({"id": gr_id}, {"$set": {"items": items, "has_unbilled_lines": True,
                                                                    "updated_at": _now()}})
    return entry


async def add_billing_deduction(db, *, gr_id: str, line_id: str, qty: float, amount: float,
                                source: str, ref_id: str = "", ref_number: str = "") -> None:
    """Potongan tagihan SEBELUM faktur (nota debit atas qty bersih yang belum ditagih)."""
    gr = await db.warehouse_receiving.find_one({"id": gr_id}, {"_id": 0})
    if not gr:
        return
    items = gr.get("items") or []
    for li in items:
        if line_id_of(li) == line_id:
            li.setdefault("billing_deductions", []).append(
                {"id": _uid(), "qty": _r4(qty), "amount": _r2(amount), "source": source,
                 "ref_id": ref_id, "ref_number": ref_number, "at": _now()})
            break
    await db.warehouse_receiving.update_one({"id": gr_id}, {"$set": {"items": items, "updated_at": _now()}})


async def receive_late(db, *, gr: dict, line: dict, qty: float, unit_price: float, location_id: str,
                       source: str, ref_id: str, ref_number: str, user: dict,
                       qty_before: float | None = None, apply_wac: bool = True) -> dict:
    """Penerimaan susulan = penerimaan biasa pada GR yang sama: Dr persediaan (per jenis) / Cr GRNI
    (profil `inventory_receive`, mesin posting yang SAMA dengan GR), HPP rata-rata diperbarui pada
    harga itu, qty dicatat bisa ditagih di baris GR, dan qty diterima PO bertambah.

    Mutasi STOK (karantina → lokasi, atau stok masuk) dikerjakan PEMANGGIL; `qty_before` = qty
    bernilai SEBELUM barang ini masuk nilai persediaan."""
    from core import accessory_valuation
    from routes.rahaza_posting import post_inventory_receive
    mid = line.get("material_id")
    mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0}) or {}
    mv = {"id": _uid(), "material_id": mid, "material_name": mat.get("name") or line.get("material_name"),
          "material_code": mat.get("code"), "unit_cost": _f(unit_price), "location_id": location_id,
          "type": "receive", "qty": _r4(qty), "unit": line.get("unit") or mat.get("unit"),
          "reference_type": "goods_receipt_late", "reference_id": gr.get("id"),
          "reference_number": gr.get("receipt_number", ""), "related_type": source, "related_ref": ref_id,
          "notes": f"Penerimaan susulan GR {gr.get('receipt_number', '')} ({source} {ref_number})".strip(),
          "created_by": user.get("id", ""), "created_by_name": user.get("name", ""),
          "created_at": _now(), "timestamp": _now()}
    await db.rahaza_material_movements.insert_one(dict(mv))
    try:
        posting = await post_inventory_receive(db, mv, user)
    except Exception as e:  # noqa: BLE001 — dicatat di dokumen, tidak menggagalkan mutasi yang sudah terjadi
        log.exception("jurnal penerimaan susulan gagal")
        posting = {"ok": False, "error": str(e)}
    wac = None
    if apply_wac and _f(unit_price) > 0:
        wac = await accessory_valuation.apply_receipt_cost(
            db, mid, _f(qty), _f(unit_price), qty_before=qty_before,
            actor={"id": user.get("id"), "name": user.get("name", "")},
            notes=f"Penerimaan susulan GR {gr.get('receipt_number', '')} · {ref_number}".strip())
    entry = await record_late_receipt(
        db, gr_id=gr["id"], line_id=line_id_of(line), qty=qty, unit_price=unit_price, source=source,
        ref_id=ref_id, ref_number=ref_number, je_number=posting.get("je_number"), actor=user)
    if gr.get("po_id"):
        try:
            from routes.rahaza_po import update_po_received_qty
            await update_po_received_qty(db, gr["po_id"], [{"material_id": mid, "po_item_id": line.get("po_item_id"),
                                                             "qty": _f(qty)}])
        except Exception:  # noqa: BLE001 — sama dengan GR: kegagalan PO tidak membatalkan penerimaan
            log.exception("update qty diterima PO (penerimaan susulan) gagal")
    return {"posting": posting, "wac": wac, "late_receipt": entry, "movement_id": mv["id"]}


def is_finance(user: dict) -> bool:
    """Keuangan (harga potongan lepas reject, nota debit, refund)."""
    from auth import check_role
    from core.roles import FINANCE_ROLES
    return check_role(user or {}, list(FINANCE_ROLES), "fin.ap.manage")
