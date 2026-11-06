"""core.purchase_costing — selisih harga pembelian MASUK HPP bahan (Tahap 2 Pengadaan, 2026-11-06).

KEPUTUSAN OWNER (6 Nov 2026)
----------------------------
Selisih harga faktur pemasok vs penerimaan (GR), PPN pemasok yang tidak dapat dikreditkan (non-PKP), dan
ongkos kirim masuk ke HPP bahan (rata-rata bergerak) — bukan lagi ke 5-1900. Model *landed cost* standar:

* nilai baris faktur = qty × harga faktur + bagian (ongkir − potongan + PPN dikapitalisasi) yang dibagi
  MENURUT NILAI baris (`allocate_landed`);
* selisih baris = nilai baris faktur − nilai baris GR (yang sudah masuk GRNI);
* bagian selisih yang barangnya MASIH ADA di persediaan → nilai persediaan (Dr/Cr 1-1401/1-1402 lawan
  hutang) dan HPP rata-rata disesuaikan lewat `accessory_valuation.apply_value_change` (fungsi revaluasi
  yang sudah ada — tidak ada rumus kedua); riwayat harga dicatat dengan sumbernya;
* bagian yang barangnya SUDAH TERPAKAI tetap di 5-1900 (biayanya sudah mengalir ke WIP/HPP penjualan).

Modul ini juga memuat koreksi stok bernilai 0 yang di-reset harga beli (`wac_receipt_gap`) supaya nilai
stok = buku besar (butir 7), dan penyerapan potongan "diterima dengan diskon" (butir 9).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Sumber riwayat harga (`rahaza_material_cost_history.source`) — labelnya di core/material_cost_history.
SOURCE_INVOICE = "invoice_variance"
SOURCE_INVOICE_VOID = "invoice_variance_void"
# Klaim posting selisih faktur yang tertinggal (proses mati di tengah) dianggap basi setelah ini.
HPP_CLAIM_STALE = timedelta(minutes=10)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v), 2)


def _now():
    return datetime.now(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# 1. FUNGSI MURNI
# ═════════════════════════════════════════════════════════════════════════════
def allocate_landed(items: list, *, freight: float = 0.0, discount: float = 0.0,
                    capitalized_tax: float = 0.0) -> tuple[list, float]:
    """Nilai *landed* tiap baris faktur + sisa yang tidak bisa dibagi (murni).

    Tambahan (ongkir − potongan + PPN dikapitalisasi) dibagi menurut nilai baris (`amount`); sisa
    pembulatan ditempel ke baris bernilai terbesar supaya Σ landed = Σ amount + tambahan. Faktur tanpa
    baris bernilai ⇒ seluruh tambahan dikembalikan sebagai `unallocated` (pemanggil → 5-1900)."""
    amounts = [_f(it.get("amount")) for it in items or []]
    extra = _r2(_f(freight) - _f(discount) + _f(capitalized_tax))
    base = sum(a for a in amounts if a > 0)
    if not amounts or base <= 0 or abs(extra) < 0.005:
        return [_r2(a) for a in amounts], (extra if abs(extra) >= 0.005 else 0.0)
    shares = [_r2(extra * a / base) if a > 0 else 0.0 for a in amounts]
    big = max(range(len(amounts)), key=lambda i: amounts[i])
    shares[big] = _r2(shares[big] + extra - sum(shares))
    return [_r2(a + s) for a, s in zip(amounts, shares)], 0.0


def on_hand_ratio(qty_basis: float, valued_qty: float) -> float:
    """Bagian selisih yang barangnya MASIH ADA = min(1, qty bernilai sekarang ÷ qty dasar) (murni).
    Barang yang sudah terpakai tidak bisa lagi menyerap selisihnya — bagian itu tetap 5-1900."""
    q, vq = max(0.0, _f(qty_basis)), max(0.0, _f(valued_qty))
    if vq <= 1e-9:
        return 0.0
    return 1.0 if q <= 1e-9 else min(1.0, vq / q)


def wac_receipt_gap(qty_before: float, old_cost: float, qty_in: float, cost_in: float,
                    new_cost: float) -> float:
    """Nilai persediaan yang BERUBAH tanpa jurnal saat penerimaan me-reset HPP (murni, butir 7).

    `moving_average` memakai harga masuk sebagai HPP baru bila stok lama bernilai 0 atau minus. Jurnal
    penerimaan hanya membukukan qty masuk × harga masuk, padahal stok lama ikut dinilai ulang:
    qty_lama × (HPP_baru − HPP_lama). Rumus SAMA dengan FG (`fg_cost_layers.wac_after_receipt`).
    Penerimaan yang dirata-rata biasa ⇒ 0 (pembulatan tidak dijurnal)."""
    qb, wb, qi, ci, nw = _f(qty_before), _f(old_cost), _f(qty_in), _f(cost_in), _f(new_cost)
    if ci <= 0 or qi <= 0:
        return 0.0
    # Penyatuan paket (6 Nov 2026): stok MINUS sudah dijurnal oleh `accessory_valuation.apply_receipt_cost`
    # (paket gudang, `negative_stock_adjustment`) di SETIAP pintu penerimaan — di sini hanya stok bernilai 0
    # yang qty-nya positif, supaya koreksi tidak terjurnal dua kali.
    reset = qb > 1e-9 and wb <= 0
    if not reset:
        return 0.0
    return _r2(qb * (nw - wb))


# ═════════════════════════════════════════════════════════════════════════════
# 2. PENYERAPAN NILAI KE STOK (DB) — satu pintu untuk selisih faktur & potongan harga
# ═════════════════════════════════════════════════════════════════════════════
async def absorb_value_change(db, material_id: str, delta: float, *, ratio: float = 1.0,
                              actor: dict | None = None, notes: str = "", source: str = SOURCE_INVOICE) -> dict:
    """Ubah nilai stok bernilai sebesar bagian `delta` yang barangnya masih ada → HPP rata-rata baru.

    Revaluasinya lewat `accessory_valuation.apply_value_change` (tidak ada rumus kedua). Angka yang
    DIKEMBALIKAN adalah perubahan nilai stok yang BENAR-BENAR terjadi (qty × (HPP baru − HPP lama),
    sesudah pembulatan HPP), supaya pemanggil membukukan angka yang sama persis ⇒ stok = buku besar.
    Return {to_inventory, to_ppv, qty, old_unit_cost, new_unit_cost}."""
    from core import accessory_valuation, quarantine
    d = _r2(delta)
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0}) or {}
    old = accessory_valuation.resolve_unit_cost(mat)
    q = _f(await quarantine.valued_onhand(db, material_id))
    out = {"to_inventory": 0.0, "to_ppv": d, "qty": round(q, 4), "old_unit_cost": round(old, 4),
           "new_unit_cost": round(old, 4)}
    if abs(d) < 0.005 or q <= 1e-9:
        return out
    target = _r2(d * max(0.0, min(1.0, _f(ratio))))
    floor = -_r2(q * old)
    if target < floor:
        target = floor
    if abs(target) < 0.005:
        return out
    res = await accessory_valuation.apply_value_change(db, material_id, target, actor=actor, notes=notes,
                                                       source=source)
    if not res.get("applied"):
        return out
    actual = _r2(_f(res.get("qty")) * (_f(res.get("new_unit_cost")) - _f(res.get("old_unit_cost"))))
    return {"to_inventory": actual, "to_ppv": _r2(d - actual), "qty": round(_f(res.get("qty")), 4),
            "old_unit_cost": round(_f(res.get("old_unit_cost")), 4),
            "new_unit_cost": round(_f(res.get("new_unit_cost")), 4)}


# ═════════════════════════════════════════════════════════════════════════════
# 3. SELISIH FAKTUR PEMASOK → HPP (DB)
# ═════════════════════════════════════════════════════════════════════════════
def invoice_material_diffs(invoice: dict, *, capitalized_tax: float = 0.0) -> tuple[dict, float]:
    """Selisih per material dari faktur dari-GR + sisa yang tidak bertuan (murni).

    Return ({material_id: {diff, qty, lines}}, sisa). Baris tanpa material (aset / item bebas) dan
    tambahan yang tidak bisa dibagi masuk `sisa` (→ 5-1900)."""
    items = list(invoice.get("items") or [])
    landed, rest = allocate_landed(items, freight=_f(invoice.get("freight_amount")),
                                   discount=_f(invoice.get("invoice_discount")),
                                   capitalized_tax=capitalized_tax)
    per: dict = {}
    for it, lv in zip(items, landed):
        diff = _r2(lv - _f(it.get("gr_amount") if it.get("gr_amount") is not None else it.get("amount")))
        mid = it.get("material_id")
        if not mid:
            rest = _r2(rest + diff)
            continue
        slot = per.setdefault(mid, {"diff": 0.0, "qty": 0.0, "lines": 0})
        slot["diff"] = _r2(slot["diff"] + diff)
        slot["qty"] = round(slot["qty"] + _f(it.get("qty")), 4)
        slot["lines"] += 1
    return per, _r2(rest)


async def claim_invoice_hpp(db, inv_id: str) -> bool:
    """Klaim atomik penerapan selisih HPP satu faktur (posting ganda tidak menggandakan revaluasi)."""
    now = _now()
    res = await db.rahaza_ap_invoices.update_one(
        {"id": inv_id, "$or": [{"hpp_adjustment.status": {"$nin": ["applying", "applied"]}},
                               {"hpp_adjustment.status": "applying",
                                "hpp_adjustment.at": {"$lt": now - HPP_CLAIM_STALE}}]},
        {"$set": {"hpp_adjustment": {"status": "applying", "at": now}}})
    return bool(res.matched_count)


async def apply_invoice_hpp(db, invoice: dict, *, capitalized_tax: float, actor: dict | None) -> dict:
    """Terapkan selisih faktur ke HPP per material. Return {lines, inventory_by_kind, to_ppv}.

    `lines[i]` = {material_id, code, kind, diff, to_inventory, to_ppv, qty, valued_qty, old, new} —
    disimpan di faktur supaya pembatalan faktur bisa membaliknya. Barang jadi (FG) tidak lewat sini
    (nilainya lapisan WAC FG milik paket HPP) ⇒ selisihnya tetap 5-1900."""
    from routes.rahaza_posting import inventory_kind
    per, rest = invoice_material_diffs(invoice, capitalized_tax=capitalized_tax)
    lines, by_kind, ppv = [], {}, rest
    note = f"Selisih faktur {invoice.get('invoice_number') or ''} · {invoice.get('vendor_name') or ''}".strip()
    for mid, slot in per.items():
        mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0}) or {}
        kind = inventory_kind(mat) if mat else "bahan"
        if not mat or kind == "fg":
            ppv = _r2(ppv + slot["diff"])
            continue
        from core import quarantine
        ratio = on_hand_ratio(slot["qty"], await quarantine.valued_onhand(db, mid))
        res = await absorb_value_change(db, mid, slot["diff"], ratio=ratio, actor=actor, notes=note,
                                        source=SOURCE_INVOICE)
        ppv = _r2(ppv + res["to_ppv"])
        if abs(res["to_inventory"]) >= 0.005:
            by_kind[kind] = _r2(by_kind.get(kind, 0.0) + res["to_inventory"])
        lines.append({"material_id": mid, "code": mat.get("code") or "", "kind": kind, "diff": slot["diff"],
                      "to_inventory": res["to_inventory"], "to_ppv": res["to_ppv"], "qty": slot["qty"],
                      "valued_qty": res["qty"], "old_unit_cost": res["old_unit_cost"],
                      "new_unit_cost": res["new_unit_cost"]})
    return {"lines": lines, "inventory_by_kind": by_kind, "to_ppv": ppv}


async def revert_invoice_hpp(db, lines: list, *, actor: dict | None, notes: str) -> None:
    """Kembalikan revaluasi yang sudah diterapkan bila jurnal fakturnya GAGAL dibuat."""
    from core import accessory_valuation
    for ln in lines or []:
        amt = _r2(ln.get("to_inventory"))
        if abs(amt) >= 0.005:
            await accessory_valuation.apply_value_change(db, ln["material_id"], -amt, actor=actor, notes=notes,
                                                         source=SOURCE_INVOICE_VOID)


async def reverse_invoice_hpp(db, invoice: dict, user: dict | None) -> dict:
    """Faktur dari GR DIBATALKAN (jurnalnya di-void) → selisih yang dulu masuk stok dibalik.

    Jurnal faktur yang di-void menghapus Dr persediaan selisihnya dari buku besar, padahal stok masih
    membawa nilai itu. Bagian yang barangnya masih ada → HPP diturunkan kembali; bagian yang barangnya
    sudah terpakai (sudah mengalir ke WIP/HPP penjualan) → jurnal Dr persediaan / Cr 5-1900 supaya buku
    besar kembali sama dengan stok. Return {ok, lines, corrections}."""
    from routes.rahaza_posting import post_inventory_value_gap
    adj = invoice.get("hpp_adjustment") or {}
    if adj.get("status") != "applied":
        return {"ok": True, "skipped": True}
    note = f"Batal faktur {invoice.get('invoice_number') or ''}".strip()
    out_lines, corrections = [], []
    for ln in adj.get("lines") or []:
        d = _r2(ln.get("to_inventory"))
        if abs(d) < 0.005:
            continue
        from core import quarantine
        ratio = on_hand_ratio(ln.get("valued_qty"), await quarantine.valued_onhand(db, ln["material_id"]))
        res = await absorb_value_change(db, ln["material_id"], -d, ratio=ratio, actor=user, notes=note,
                                        source=SOURCE_INVOICE_VOID)
        gap = _r2(d + res["to_inventory"])   # bagian yang tidak bisa diturunkan dari stok (sudah terpakai)
        corr = None
        if abs(gap) >= 0.01:
            corr = await post_inventory_value_gap(
                db, material_id=ln["material_id"], amount=gap, counter="ppv",
                source_ref=f"aphpp_void:{invoice.get('id')}:{ln['material_id']}",
                memo=f"{note} — selisih harga yang sudah terpakai ({ln.get('code') or ''})", user=user or {})
            corrections.append({"material_id": ln["material_id"], "amount": gap,
                                "je_number": (corr or {}).get("je_number"), "error": (corr or {}).get("error")})
        out_lines.append({**ln, "reversed_inventory": res["to_inventory"], "reversed_gap": gap})
    await db.rahaza_ap_invoices.update_one(
        {"id": invoice.get("id")},
        {"$set": {"hpp_adjustment.status": "reversed", "hpp_adjustment.reversed_at": _now(),
                  "hpp_adjustment.reversal": {"lines": out_lines, "corrections": corrections}}})
    return {"ok": all(not c.get("error") for c in corrections), "lines": out_lines, "corrections": corrections}


# ═════════════════════════════════════════════════════════════════════════════
# 4. STOK BERNILAI 0 DI-RESET HARGA BELI → JURNAL KOREKSI (butir 7)
# ═════════════════════════════════════════════════════════════════════════════
async def post_receipt_wac_gap(db, *, material_id: str, cost_result: dict | None, qty_in: float,
                               cost_in: float, source_ref: str, memo: str, user: dict | None) -> dict | None:
    """Jurnal Dr/Cr persediaan ↔ 5-1950 sebesar `wac_receipt_gap` (None bila tidak ada selisih).

    Dipanggil SESUDAH `accessory_valuation.apply_receipt_cost` di setiap pintu pembelian (GR, penerimaan
    susulan, penerimaan manual). Tidak pernah melempar — kegagalan dikembalikan sebagai hasil posting."""
    res = cost_result or {}
    gap = wac_receipt_gap(res.get("qty_before"), res.get("old_unit_cost"), qty_in, cost_in,
                          res.get("new_unit_cost"))
    if abs(gap) < 0.01:
        return None
    try:
        from routes.rahaza_posting import post_inventory_value_gap
        return await post_inventory_value_gap(db, material_id=material_id, amount=gap, counter="adjustment",
                                              source_ref=f"wacgap:{source_ref}", memo=memo, user=user or {})
    except Exception as e:  # noqa: BLE001 — penerimaan sudah terjadi; kegagalan dicatat, bukan dilempar
        log.exception("jurnal koreksi stok bernilai 0 gagal (material=%s)", material_id)
        return {"ok": False, "error": str(e)}
