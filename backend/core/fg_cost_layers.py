"""core/fg_cost_layers.py — **SSOT HPP barang jadi: rata-rata bergerak (WAC)** + lapisan
biaya per batch (jejak analitik).

2026-11-02 — KEPUTUSAN OWNER No.26(a): WAC untuk SEMUA persediaan
------------------------------------------------------------------
Bahan sudah WAC (`core/accessory_valuation.moving_average`). Barang jadi dulu FIFO
lapisan; sekarang memakai rumus WAC YANG SAMA (tidak ditulis ulang di sini):

    WAC baru = (qty lama × WAC lama + qty masuk × biaya masuk) / (qty lama + qty masuk)
    HPP keluar = qty × WAC saat itu (WAC tidak berubah karena barang keluar)

* **Satu tempat**: `rahaza_materials.unit_cost` (field biaya yang sudah ada; FG dulu
  kosong) = WAC per pcs, plus `wac_components` {material, labor, overhead} per pcs
  (Σ = unit_cost) supaya jurnal HPP tetap terpecah ke 5-1000/5-2000/5-3500.
  `hpp` master FG TIDAK lagi ditimpa angka aktual — ia tinggal HPP kalkulator
  (estimasi), jadi tombol "Terapkan HPP per Potong" tidak bisa menimpa WAC.
* **qty lama** = stok FG milik DA yang bernilai, lintas lokasi (:func:`valued_qty`):
  semua baris material ini KECUALI lokasi/baris karantina-terblokir (barang rusak
  bernilai 0) dan baris milik pihak lain (titipan maklon).
* **Barang masuk** (Terima FG dari CMT, retur diterima, retur penjualan langsung,
  barang kembali) lewat :func:`push_layer` → lapisan batch dicatat + WAC diperbarui.
* **Barang keluar** (nota penjualan langsung, kirim buyer, fulfillment, kelak scan
  keluar K15) lewat :func:`issue_wac` (nama lama `consume_fifo` dipertahankan untuk
  pemanggil di berkas lain) → nilai = qty × WAC.
* Lapisan (`fg_cost_layers`) tetap lahir per batch dan `qty_remaining`-nya tetap
  berkurang urut-tertua sebagai JEJAK analitik (batch mana yang masih ada, biaya
  per SPK) — angkanya TIDAK lagi dipakai untuk HPP.

ATURAN JUJUR (sama dengan bahan)
--------------------------------
1. Biaya masuk Rp 0 (BOM/jahit belum ada) **tidak mengubah WAC** — biaya tidak
   diketahui bukan berarti gratis. 2026-11-06 (Tahap 2): pcs itu dinilai WAC berjalan
   DENGAN jurnal koreksi (1-1404 lawan 5-1950); bila WAC masih 0, stoknya "tanpa biaya"
   sampai biaya pertama datang, lalu nilainya diakui dengan jurnal koreksi yang sama.
2. **Stok minus / nol (Stok Boleh Minus ON)**: qty lama ≤ 0 ⇒ biaya masuk menjadi
   WAC baru. Bila qty lama < 0, barang yang keluar saat minus sudah dinilai WAC
   lama; selisihnya `qty_lama × (biaya_masuk − WAC_lama)` dibukukan ke 5-1950
   Selisih Persediaan lawan 1-1404 (:func:`wac_after_receipt`), sehingga
   Σ stok × WAC tetap = saldo GL 1-1404.
3. WAC 0 (belum pernah ada biaya nyata) ⇒ barang keluar dicatat `uncosted_qty`,
   tidak ditebak dengan HPP kalkulator.
4. Lapisan tidak pernah dihapus; komponen biaya yang tidak diketahui ditulis 0 dan
   dicatat di `gaps[]`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

LAYERS = "fg_cost_layers"
CONSUMPTIONS = "fg_cost_consumptions"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def _f(v, d: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(d)
        return float(v)
    except (TypeError, ValueError):
        return float(d)


def _r(v, nd: int = 2) -> float:
    return round(_f(v), nd)


# ══════════════════════════════════════════════════════════════════════════════
# MENGHITUNG BIAYA SATU BATCH
# ══════════════════════════════════════════════════════════════════════════════
def permak_to_absorb(rows: list | None) -> list:
    """Sisa ongkos tiap dokumen permak yang belum dibebankan ke lapisan mana pun (murni).

    sisa = total_cost (atau cost_per_pcs × qty) − permak_absorbed_cost. Bila ongkos permak
    dinaikkan setelah diserap, hanya selisihnya yang ikut batch berikutnya."""
    out = []
    for r in rows or []:
        total = _f(r.get("total_cost")) or _f(r.get("cost_per_pcs")) * _f(r.get("qty"))
        left = round(total - _f(r.get("permak_absorbed_cost")), 2)
        if r.get("id") and left > 0:
            out.append({"id": r["id"], "amount": left})
    return out


async def compute_batch_unit_cost(db, *, po_item: dict, qty: int) -> dict:
    """Biaya per pcs satu batch = bahan (BOM) + upah jahit (SPK) + permak (Tahap 2: tanpa upah internal).

    Semua komponen menyebut ASALNYA. Komponen yang belum ada tidak ditebak.
    """
    from core import product_costing as pc

    out = {
        "material_cost": 0.0, "material_source": "none",
        "sewing_cost": 0.0, "sewing_source": "none",
        "permak_cost": 0.0, "permak_source": "none",
        "internal_labor_cost": 0.0, "internal_labor_source": "none",
        "overhead_cost": 0.0,
        "unit_cost": 0.0, "gaps": [],
    }
    model_id = (po_item or {}).get("model_id") or ""
    size_id = (po_item or {}).get("size_id") or ""

    # ── bahan: BOM × harga master (SSOT core/product_costing) ────────────────
    if model_id and size_id:
        try:
            mc = await pc.compute_material_cost(db, model_id, size_id)
            if mc.get("bom_id"):
                out["material_cost"] = _r(mc.get("material_cost"))
                out["material_source"] = "bom"
                if mc.get("unvalued_count"):
                    out["gaps"].append(
                        f"{mc['unvalued_count']} bahan belum punya harga — biaya bahan batch ini "
                        f"lebih rendah dari kenyataan")
            else:
                out["gaps"].append("BOM model/ukuran ini belum ada — biaya bahan batch belum bisa dihitung")
        except Exception:  # noqa: BLE001
            logger.exception("compute_material_cost gagal (model=%s size=%s)", model_id, size_id)
            out["gaps"].append("biaya bahan gagal dihitung — periksa BOM & satuan bahan")
    else:
        out["gaps"].append("item SPK tidak menunjuk model/ukuran — biaya bahan tidak bisa dihitung")

    # ── upah jahit: DIINPUT di SPK (po_items.cmt_price_snapshot) ─────────────
    rate = _f((po_item or {}).get("cmt_price_snapshot"))
    if rate > 0:
        out["sewing_cost"] = _r(rate)
        out["sewing_source"] = "spk"
    else:
        out["gaps"].append("biaya jahit/pcs SPK ini belum diisi — isi di layar Biaya Jahit SPK")

    # ── permak: ongkos perbaikan item ini yang BELUM masuk batch mana pun ────
    # Tahap 1 (6 Nov 2026): dulu SEMUA permak item SPK dibagi qty batch INI pada setiap
    # penerimaan (permak Rp20.000 → terima 45 pcs lalu 5 pcs = Rp40.000 terbebankan).
    # Sekarang hanya sisa yang belum diserap (`permak_absorbed_cost`); `push_layer`
    # menandai dokumen permak begitu lapisannya tercatat, jadi tiap rupiah dibebankan sekali.
    out["permak_absorb"] = []
    pid = (po_item or {}).get("id")
    if pid and qty > 0:
        rows = await db.dewi_cmt_permak.find(
            {"po_item_id": pid}, {"_id": 0, "id": 1, "total_cost": 1, "cost_per_pcs": 1, "qty": 1,
                                  "permak_absorbed_cost": 1}
        ).to_list(500)
        absorb = permak_to_absorb(rows)
        total = sum(a["amount"] for a in absorb)
        if total > 0:
            out["permak_cost"] = _r(total / qty)
            out["permak_source"] = f"permak ({len(absorb)} dokumen, dibagi {qty} pcs batch)"
            out["permak_absorb"] = absorb

    # ── upah internal (cutting dll) + overhead: TIDAK masuk HPP ──────────────
    # 2026-11-06 (Tahap 2, keputusan owner): dulu upah internal & overhead kalkulator ikut
    # lapisan FG (Cr WIP), padahal payroll sudah membukukannya ke 6-2100 → terhitung dua kali.
    # Keduanya tetap beban bulanan; kuncinya dipertahankan (0) supaya pembaca lama tetap jalan.
    out["internal_labor_source"] = "tidak masuk HPP"

    out["unit_cost"] = _r(out["material_cost"] + out["sewing_cost"] + out["permak_cost"])
    return out


# ══════════════════════════════════════════════════════════════════════════════
# WAC — RUMUS MURNI (2026-11-02, keputusan owner No.26a; diuji tanpa DB)
# ══════════════════════════════════════════════════════════════════════════════
COMP_KEYS = ("material", "labor", "overhead")
WAC_FIELD = "unit_cost"            # field biaya yang sudah ada; FG dulu kosong
WAC_COMPONENTS = "wac_components"  # {material, labor, overhead} per pcs, Σ = unit_cost
DA_OWNERSHIP = (None, "", "cv_da", "own")   # baris stok milik DA (bukan titipan maklon)
_STALE_FIFO_FIELDS = {"hpp_fifo_avg": "", "hpp_last_batch": "", "hpp_layer_qty": ""}


def _zero_comps() -> dict:
    return {k: 0.0 for k in COMP_KEYS}


def _fit(comps: dict | None, total: float, nd: int = 4) -> dict:
    """Bulatkan komponen; sisa pembulatan ditempel ke BAHAN supaya Σ komponen = total."""
    out = {k: round(_f((comps or {}).get(k)), nd) for k in COMP_KEYS}
    out["material"] = round(out["material"] + round(_f(total), nd) - sum(out.values()), nd)
    return out


def components_from_breakdown(breakdown: dict | None, unit_cost: float,
                              fallback: dict | None = None) -> dict:
    """Rincian biaya → komponen per pcs {material, labor, overhead} dengan Σ = unit_cost.

    Menerima rincian batch (`material_cost`, `sewing_cost`, `permak_cost`,
    `internal_labor_cost`, `overhead_cost`) ATAU komponen jadi (`material`/`labor`/
    `overhead`). Tanpa rincian ⇒ proporsi `fallback` (komponen WAC saat ini), lalu
    seluruhnya BAHAN — aturan yang sama dengan jurnal HPP lama."""
    uc = _f(unit_cost)
    if uc <= 0:
        return _zero_comps()
    bd = breakdown or {}
    if any(k in bd for k in COMP_KEYS):
        raw = {k: _f(bd.get(k)) for k in COMP_KEYS}
    else:
        raw = {"material": _f(bd.get("material_cost")),
               "labor": (_f(bd.get("sewing_cost")) + _f(bd.get("permak_cost"))
                         + _f(bd.get("internal_labor_cost"))),
               "overhead": _f(bd.get("overhead_cost"))}
    if sum(raw.values()) <= 0:
        raw = {k: _f((fallback or {}).get(k)) for k in COMP_KEYS}
    s = sum(raw.values())
    if s <= 0:
        return _fit({"material": uc}, uc)
    return _fit({k: v * uc / s for k, v in raw.items()}, uc)


def initial_wac_from_layers(layers: list | None) -> dict:
    """WAC awal satu FG dari lapisan yang ada (migrasi No.26):
    Σ qty_remaining × unit_cost / Σ qty_remaining — sama dengan nilai lapisan yang
    sudah dibukukan ke 1-1404, jadi rekonsiliasi tidak bergeser saat pindah metode.
    Lapisan Rp 0 ikut dihitung (nilainya memang 0 di GL) dan DILAPORKAN."""
    open_rows = [ly for ly in (layers or []) if _f(ly.get("qty_remaining")) > 0]
    qty = sum(_f(ly.get("qty_remaining")) for ly in open_rows)
    value = sum(_f(ly.get("qty_remaining")) * _f(ly.get("unit_cost")) for ly in open_rows)
    acc = _zero_comps()
    for ly in open_rows:
        c = components_from_breakdown(ly.get("breakdown"), ly.get("unit_cost"))
        for k in COMP_KEYS:
            acc[k] += c[k] * _f(ly.get("qty_remaining"))
    uc = round(value / qty, 4) if qty > 0 else 0.0
    zero = [ly for ly in open_rows if _f(ly.get("unit_cost")) <= 0]
    return {"unit_cost": uc,
            "components": _fit({k: v / qty for k, v in acc.items()}, uc) if qty > 0 else _zero_comps(),
            "qty": qty, "value": round(value, 2), "open_layers": len(open_rows),
            "zero_cost_layers": len(zero),
            "zero_cost_qty": sum(_f(ly.get("qty_remaining")) for ly in zero)}


def wac_after_receipt(qty_before, wac_before, comps_before, qty_in, cost_in,
                      comps_in: dict | None = None) -> dict:
    """WAC setelah barang masuk — rumus `accessory_valuation.moving_average` (SSOT bahan).

    `adjustment_fg` = nilai yang harus DIDEBIT ke 1-1404 (negatif = dikredit) lawan
    5-1950 Selisih Persediaan. Hanya ≠ 0 bila qty lama < 0 (Stok Boleh Minus ON):
    pcs yang keluar saat minus sudah dinilai WAC lama, padahal biaya nyatanya =
    biaya masuk ini ⇒ selisih = qty_lama × (biaya_masuk − WAC_lama). Dengan begitu
    Σ stok × WAC baru = saldo GL 1-1404 setelah jurnal penerimaan + jurnal ini.

    2026-11-06 (Tahap 2) — SATU aturan stok tanpa biaya: setiap kali WAC mengubah nilai stok yang
    belum pernah dijurnal, selisihnya DIJURNAL (1-1404 lawan 5-1950), jadi Σ stok × WAC = GL:
      * barang masuk Rp 0 ke stok yang sudah ber-WAC (`zero_cost_at_wac`) → WAC tetap, pcs itu
        dinilai WAC berjalan: selisih = qty masuk × WAC;
      * stok tanpa biaya (WAC 0) lalu biaya pertama datang (`reset_unvalued`) → WAC = biaya masuk,
        pcs yang menunggu biaya diakui: selisih = qty lama × biaya masuk (jurnal koreksi).
    Stok tanpa biaya yang WAC-nya masih 0 tetap `keep_zero_cost` (tanpa jurnal; keluar = uncosted)."""
    from core.accessory_valuation import moving_average
    qb, wb, qi, ci = _f(qty_before), _f(wac_before), _f(qty_in), _f(cost_in)
    cb = _fit(comps_before or {"material": wb}, wb) if wb > 0 else _zero_comps()
    cin = components_from_breakdown(comps_in, ci, fallback=cb)
    new = moving_average(qb, wb, qi, ci)
    adj = 0.0
    if ci <= 0:
        rule, comps, new = "keep_zero_cost", cb, round(wb, 4)
        if wb > 0 and qi > 0:
            rule, adj = "zero_cost_at_wac", round(qi * wb, 2)
    elif qb <= 0 or wb <= 0:
        rule = "reset_negative" if qb < 0 else ("reset_empty" if qb == 0 else "reset_unvalued")
        comps = cin
        if qb < 0:
            adj = round(qb * (ci - wb), 2)
        elif rule == "reset_unvalued":
            adj = round(qb * ci, 2)
    else:
        rule = "weighted"
        comps = _fit({k: (qb * cb[k] + qi * cin[k]) / (qb + qi) for k in COMP_KEYS}, new)
    return {"unit_cost": round(new, 4), "components": comps, "rule": rule,
            "adjustment_fg": adj, "qty_before": qb, "wac_before": round(wb, 4),
            "qty_in": qi, "cost_in": round(ci, 4), "qty_after": qb + qi}


def wac_after_reversal(qty_after, wac, comps, qty_out, cost_out) -> dict:
    """WAC setelah SATU penerimaan dibatalkan (stoknya sudah dikeluarkan pemanggil) dengan
    nilai keluar = qty × biaya masuk asal, bukan WAC saat ini — supaya jurnal pembalik
    (cermin jurnal penerimaan) dan Σ stok × WAC tetap sama. Bila stok habis/minus,
    sisa nilainya menjadi `adjustment_fg` (5-1950)."""
    qa, w, qo, co = _f(qty_after), _f(wac), _f(qty_out), _f(cost_out)
    c = _fit(comps or {"material": w}, w) if w > 0 else _zero_comps()
    cin = components_from_breakdown(None, co, fallback=c)
    v_after = (qa + qo) * w - qo * co
    new, comps_new = w, c
    if qa > 0 and v_after >= 0:
        new = v_after / qa
        comps_new = _fit({k: max(0.0, ((qa + qo) * c[k] - qo * cin[k]) / qa) for k in COMP_KEYS}, new)
    adj = round(qa * round(new, 4) - v_after, 2)
    return {"unit_cost": round(new, 4), "components": comps_new, "rule": "reverse_receipt",
            "adjustment_fg": adj if abs(adj) >= 0.01 else 0.0, "qty_before": qa + qo,
            "wac_before": round(w, 4), "qty_out": qo, "cost_out": round(co, 4), "qty_after": qa}


def value_issue(qty, wac, comps) -> dict:
    """Nilai barang keluar = qty × WAC, dipecah per komponen (Σ komponen = cogs)."""
    q, w = _f(qty), _f(wac)
    if q <= 0 or w <= 0:
        return {"cogs": 0.0, "components": _zero_comps(),
                "uncosted_qty": int(q) if (q > 0 and w <= 0) else 0}
    cogs = round(q * w, 2)
    c = _fit(comps or {"material": w}, w)
    return {"cogs": cogs, "components": _fit({k: q * c[k] for k in COMP_KEYS}, cogs, nd=2),
            "uncosted_qty": 0}


def split_issue_entries(qty: int, wac: float, valued: dict, trail: list) -> list:
    """Baris `layers_used` keluaran :func:`issue_wac`: jejak batch (FIFO, analitik) yang
    masing-masing DINILAI WAC. Σ total = cogs dan Σ komponen = komponen cogs. Qty yang
    tidak tertutup lapisan tetap dinilai WAC (baris `layer_id` kosong)."""
    parts = [dict(t) for t in (trail or []) if _f(t.get("qty")) > 0]
    covered = sum(int(_f(t["qty"])) for t in parts)
    if qty - covered > 0:
        parts.append({"layer_id": "", "qty": qty - covered, "batch_unit_cost": None, "po_number": ""})
    out, acc_total, acc = [], 0.0, _zero_comps()
    for i, p in enumerate(parts):
        if i == len(parts) - 1:
            total = round(valued["cogs"] - acc_total, 2)
            comps = {k: round(valued["components"][k] - acc[k], 2) for k in COMP_KEYS}
        else:
            share = _f(p["qty"]) / qty
            total = round(valued["cogs"] * share, 2)
            comps = _fit({k: valued["components"][k] * share for k in COMP_KEYS}, total, nd=2)
        acc_total = round(acc_total + total, 2)
        acc = {k: round(acc[k] + comps[k], 2) for k in COMP_KEYS}
        out.append({"layer_id": p.get("layer_id") or "", "qty": int(_f(p["qty"])),
                    "unit_cost": round(_f(wac), 4), "total": total, "components": comps,
                    "basis": "wac", "batch_unit_cost": p.get("batch_unit_cost"),
                    "po_number": p.get("po_number") or ""})
    return out


def is_valued_row(row: dict, blocked_locs: set) -> bool:
    """Baris stok FG yang ikut "qty lama" WAC: bukan karantina/terblokir, milik DA."""
    from core.catalog_stock import row_is_sellable
    return row_is_sellable(row, blocked_locs) and row.get("ownership") in DA_OWNERSHIP


def valued_qty(rows: list | None, blocked_locs: set) -> float:
    from core.stock_schema import read_qty
    return round(sum(read_qty(r) for r in (rows or []) if is_valued_row(r, blocked_locs)), 4)


# ══════════════════════════════════════════════════════════════════════════════
# WAC — KEADAAN DI MASTER FG
# ══════════════════════════════════════════════════════════════════════════════
async def valued_onhand(db, material_id: str) -> float:
    """Σ stok FG milik DA yang bernilai, lintas lokasi (dasar "qty lama" WAC)."""
    from core import catalog_stock, stock_service
    rows = await stock_service.list_rows(material_id, db=db)
    return valued_qty(rows, await catalog_stock.blocked_location_ids(db))


async def _history(db, *, material_id, old, new, qty_before, qty_in, cost_in, source, actor, notes):
    """Riwayat perubahan WAC di koleksi riwayat harga yang SAMA dengan bahan."""
    try:
        from core.accessory_valuation import _record_history
        await _record_history(db, material_id=material_id, old_cost=old, new_cost=new,
                              qty_before=qty_before, qty_in=qty_in, cost_in=cost_in,
                              source=source, actor=actor, notes=notes)
    except Exception:  # noqa: BLE001 — riwayat tidak boleh menggagalkan mutasi
        logger.exception("riwayat WAC FG gagal dicatat (material=%s)", material_id)


async def wac_state(db, material_id: str, *, init: bool = True, actor: dict | None = None) -> dict:
    """WAC saat ini satu FG. FG yang BELUM pernah dinilai WAC diinisialisasi sekali dari
    lapisan yang ada (rumus :func:`initial_wac_from_layers`, sama dengan skrip migrasi)
    — jadi kode ini aman berjalan walau migrasi belum dijalankan."""
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0}) or {}
    if isinstance(mat.get(WAC_COMPONENTS), dict):
        uc = round(_f(mat.get(WAC_FIELD)), 4)
        return {"material_id": material_id, "unit_cost": uc,
                "components": _fit(mat[WAC_COMPONENTS], uc) if uc > 0 else _zero_comps(),
                "initialized": True, "source": mat.get("wac_source") or "wac"}
    layers = await db[LAYERS].find({"material_id": material_id, "qty_remaining": {"$gt": 0}},
                                   {"_id": 0}).to_list(5000)
    ini = initial_wac_from_layers(layers)
    uc, comps = ini["unit_cost"], ini["components"]
    src = "init_from_layers" if ini["qty"] > 0 else "none"
    legacy = _f(mat.get(WAC_FIELD))
    if ini["qty"] <= 0 and legacy > 0:
        uc, comps, src = round(legacy, 4), _fit({"material": legacy}, legacy), "legacy_unit_cost"
    state = {"material_id": material_id, "unit_cost": uc, "components": comps,
             "initialized": False, "source": src, "init": ini}
    # FG tanpa lapisan & tanpa biaya lama: tidak ada yang diinisialisasi (jangan tulis unit_cost 0
    # — pembaca lain memperlakukan 0 sebagai "sudah dinilai Rp 0"); penerimaan pertama yang menulis.
    if init and mat and src != "none":
        await db.rahaza_materials.update_one({"id": material_id}, {
            "$set": {WAC_FIELD: uc, WAC_COMPONENTS: comps, "wac_source": src,
                     "cost_method": "moving_average", "wac_initialized_at": _now(),
                     "wac_updated_at": _now()},
            "$unset": dict(_STALE_FIFO_FIELDS)})
        if abs(uc - legacy) > 1e-6:
            await _history(db, material_id=material_id, old=legacy, new=uc, qty_before=ini["qty"],
                           qty_in=0, cost_in=uc, source="adjust", actor=actor,
                           notes=f"WAC FG awal ({src}) — keputusan owner No.26")
        state["initialized"] = True
    return state


async def _sync_catalog(db, material_id: str, unit_cost: float) -> None:
    """Cache HPP item katalog = WAC aktual (dibaca margin/marketing). Master `hpp` FG
    tidak disentuh: itu HPP kalkulator (estimasi)."""
    if _f(unit_cost) <= 0:
        return
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0, "code": 1}) or {}
    ors = [{"fg_material_id": material_id}, {"fg_product_id": material_id}, {"material_id": material_id}]
    if mat.get("code"):
        ors.append({"sku": mat["code"]})
    await db.marketing_catalog_items.update_many(
        {"$or": ors}, {"$set": {"hpp": _r(unit_cost), "hpp_source": "wac", "hpp_updated_at": _now()},
                       "$unset": {"hpp_fifo_avg": "", "hpp_last_batch": ""}})


async def _post_adjustment(db, *, material_id: str, res: dict, key: str, ref: dict | None,
                           actor: dict | None) -> dict:
    try:
        from routes.rahaza_posting import post_fg_wac_adjustment
        return await post_fg_wac_adjustment(db, material_id=material_id, amount=res["adjustment_fg"],
                                            source_ref=f"fg_wac_adj:{key}", detail=res,
                                            ref=ref or {}, user=actor or {})
    except Exception as e:  # noqa: BLE001
        logger.exception("jurnal selisih WAC FG gagal (material=%s)", material_id)
        return {"ok": False, "error": str(e)}


async def _save_wac(db, *, material_id: str, state: dict, res: dict, ref: dict | None,
                    actor: dict | None, key: str, source: str) -> dict:
    """Tulis WAC baru ke master + riwayat + jurnal selisih (bila ada) + cache katalog."""
    ref = ref or {}
    ref_type = ref.get("type") or ref.get("source") or ""
    last = {k: res.get(k) for k in ("rule", "qty_before", "wac_before", "qty_in", "cost_in",
                                    "qty_out", "cost_out", "qty_after", "adjustment_fg")}
    last.update({"ref_type": ref_type, "key": key, "at": _now()})
    await db.rahaza_materials.update_one({"id": material_id}, {
        "$set": {WAC_FIELD: res["unit_cost"], WAC_COMPONENTS: res["components"],
                 "wac_source": "wac", "cost_method": "moving_average", "wac_updated_at": _now(),
                 "wac_last": last},
        "$unset": dict(_STALE_FIFO_FIELDS)})
    if abs(res["unit_cost"] - state["unit_cost"]) > 1e-6:
        await _history(db, material_id=material_id, old=state["unit_cost"], new=res["unit_cost"],
                       qty_before=res.get("qty_before"),
                       qty_in=res.get("qty_in") or -_f(res.get("qty_out")),
                       cost_in=res.get("cost_in") or res.get("cost_out"), source=source,
                       actor=actor, notes=f"WAC FG {res['rule']} · {ref_type or '-'}")
    res["adjustment_je"] = None
    if abs(_f(res.get("adjustment_fg"))) >= 0.01:
        res["adjustment_je"] = await _post_adjustment(db, material_id=material_id, res=res, key=key,
                                                      ref=ref, actor=actor)
    await _sync_catalog(db, material_id, res["unit_cost"])
    return res


# ══════════════════════════════════════════════════════════════════════════════
# BARANG MASUK — lapisan batch (jejak) + WAC
# ══════════════════════════════════════════════════════════════════════════════
async def push_layer(db, *, material_id: str, qty: int, po_item: dict | None = None,
                     ref: dict | None = None, actor: dict | None = None,
                     unit_cost: float | None = None,
                     breakdown: dict | None = None,
                     components: dict | None = None) -> dict:
    """Catat satu lapisan biaya batch untuk FG `material_id` DAN perbarui WAC-nya.

    Semua pemanggil (`post_fg_accepted`, retur diterima, retur penjualan langsung) sudah
    MENAMBAH stoknya lebih dulu, jadi qty lama = stok bernilai − qty ini.
    `components` (opsional) = komponen per pcs; tanpa itu dipakai rincian batch."""
    qty = int(_f(qty))
    if not material_id or qty <= 0:
        return {}
    # inisialisasi WAC (bila FG belum pernah dinilai) SEBELUM lapisan baru ikut terhitung
    state = await wac_state(db, material_id, actor=actor)
    if unit_cost is None:
        calc = await compute_batch_unit_cost(db, po_item=po_item or {}, qty=qty)
        unit_cost = calc["unit_cost"]
        breakdown = calc
    doc = {
        "id": _uid(),
        "material_id": material_id,
        "sku": (po_item or {}).get("sku") or "",
        "model_id": (po_item or {}).get("model_id") or "",
        "size_id": (po_item or {}).get("size_id") or "",
        "qty_in": qty,
        "qty_remaining": qty,
        "unit_cost": _r(unit_cost),
        "total_cost": _r(_f(unit_cost) * qty),
        "breakdown": {k: v for k, v in (breakdown or {}).items() if k not in ("gaps", "permak_absorb")},
        "gaps": (breakdown or {}).get("gaps") or [],
        "permak_absorbed": list((breakdown or {}).get("permak_absorb") or []),
        "batch": {
            "po_id": (po_item or {}).get("po_id") or (ref or {}).get("po_id") or "",
            "po_number": (po_item or {}).get("po_number") or (ref or {}).get("po_number") or "",
            "po_item_id": (po_item or {}).get("id") or "",
            "receipt_id": (ref or {}).get("receipt_id") or "",
            "receipt_code": (ref or {}).get("receipt_code") or "",
            "source": (ref or {}).get("type") or "production",
        },
        "created_at": _now(),
        "created_by": (actor or {}).get("name") or (actor or {}).get("email") or "system",
    }
    await db[LAYERS].insert_one(doc)
    doc.pop("_id", None)
    # ongkos permak yang ikut lapisan ini ditandai SUDAH diserap (sekali saja)
    for a in doc["permak_absorbed"]:
        await db.dewi_cmt_permak.update_one({"id": a["id"]}, {
            "$inc": {"permak_absorbed_cost": _r(a["amount"])},
            "$addToSet": {"permak_absorbed_layer_ids": doc["id"]}})
    qty_before = await valued_onhand(db, material_id) - qty
    res = wac_after_receipt(qty_before, state["unit_cost"], state["components"], qty,
                            _f(unit_cost), components if components is not None else breakdown)
    res = await _save_wac(db, material_id=material_id, state=state, res=res, ref=ref, actor=actor,
                          key=doc["id"],
                          source="return" if "return" in str(doc["batch"]["source"]) else "receive")
    await db[LAYERS].update_one({"id": doc["id"]}, {"$set": {
        "wac_after": res["unit_cost"], "wac_rule": res["rule"]}})
    # 2026-11-06 (Tahap 2): pcs tanpa biaya yang sudah dinilai lewat jurnal koreksi WAC ditandai,
    # supaya Laporan Nilai Persediaan FG tidak lagi menghitungnya "tanpa biaya".
    if (res.get("adjustment_je") or {}).get("ok") and res["rule"] in ("zero_cost_at_wac", "reset_unvalued"):
        q = ({"id": doc["id"]} if res["rule"] == "zero_cost_at_wac" else
             {"material_id": material_id, "unit_cost": {"$lte": 0}, "qty_remaining": {"$gt": 0}})
        await db[LAYERS].update_many(q, {"$set": {"wac_valued": True,
                                                  "wac_valued_je_id": res["adjustment_je"].get("je_id")}})
    doc["wac"] = {k: res[k] for k in ("unit_cost", "components", "rule", "qty_before",
                                      "wac_before", "adjustment_fg")}
    doc["wac"]["adjustment_je_id"] = (res.get("adjustment_je") or {}).get("je_id")
    return doc


async def reverse_receipt(db, *, material_id: str, qty: float, unit_cost: float,
                          ref: dict | None = None, actor: dict | None = None) -> dict:
    """Batalkan satu penerimaan yang stoknya SUDAH dikeluarkan pemanggil (mis. Balik
    Keputusan retur): WAC dihitung ulang tanpa nilai penerimaan itu (:func:`wac_after_reversal`)."""
    if not material_id or _f(qty) <= 0:
        return {}
    state = await wac_state(db, material_id, actor=actor)
    res = wac_after_reversal(await valued_onhand(db, material_id), state["unit_cost"],
                             state["components"], qty, unit_cost)
    key = f"rev:{(ref or {}).get('id') or (ref or {}).get('ref_id') or _uid()}"
    return await _save_wac(db, material_id=material_id, state=state, res=res, ref=ref,
                           actor=actor, key=key, source="adjust")


# ══════════════════════════════════════════════════════════════════════════════
# BARANG KELUAR — nilai WAC (+ jejak batch FIFO analitik)
# ══════════════════════════════════════════════════════════════════════════════
async def _trail_fifo(db, material_id: str, qty: int) -> list:
    """Kurangi `qty_remaining` lapisan tertua (JEJAK batch, bukan dasar HPP)."""
    left, out = qty, []
    layers = await db[LAYERS].find(
        {"material_id": material_id, "qty_remaining": {"$gt": 0}},
        {"_id": 0}).sort("created_at", 1).to_list(500)
    for ly in layers:
        if left <= 0:
            break
        take = min(left, int(_f(ly.get("qty_remaining"))))
        if take <= 0:
            continue
        await db[LAYERS].update_one({"id": ly["id"]},
                                    {"$inc": {"qty_remaining": -take},
                                     "$set": {"updated_at": _now()}})
        out.append({"layer_id": ly["id"], "qty": take, "batch_unit_cost": _r(ly.get("unit_cost")),
                    "po_number": (ly.get("batch") or {}).get("po_number") or ""})
        left -= take
    return out


async def issue_wac(db, *, material_id: str, qty: int, ref: dict | None = None,
                    actor: dict | None = None) -> dict:
    """Nilai barang FG keluar = qty × WAC saat itu (WAC tidak berubah).

    Bentuk keluaran sama dengan versi FIFO lama (`cogs`, `layers_used`, `uncosted_qty`)
    sehingga pemanggil di berkas lain tetap jalan; tiap baris `layers_used` kini
    membawa `components` dan `basis='wac'`. `uncosted_qty` > 0 HANYA bila WAC = 0."""
    qty = int(_f(qty))
    out = {"material_id": material_id, "qty": qty, "cogs": 0.0, "unit_cost": 0.0,
           "basis": "wac", "components": _zero_comps(), "layers_used": [], "uncosted_qty": 0}
    if not material_id or qty <= 0:
        return out
    state = await wac_state(db, material_id, actor=actor)
    val = value_issue(qty, state["unit_cost"], state["components"])
    trail = await _trail_fifo(db, material_id, qty)
    out.update({"cogs": val["cogs"], "unit_cost": state["unit_cost"],
                "components": val["components"], "uncosted_qty": val["uncosted_qty"],
                "layers_used": split_issue_entries(qty, state["unit_cost"], val, trail)})
    await db[CONSUMPTIONS].insert_one({
        "id": _uid(), "material_id": material_id, "qty": qty, "basis": "wac",
        "unit_cost": out["unit_cost"], "cogs": out["cogs"], "components": out["components"],
        "uncosted_qty": out["uncosted_qty"], "layers_used": out["layers_used"], "ref": ref or {},
        "actor": (actor or {}).get("name") or "system", "created_at": _now(),
    })
    return out


# Nama lama — dipanggil `production_qty_ledger.issue_fg` & `routes/fulfillment.py`.
consume_fifo = issue_wac


# ══════════════════════════════════════════════════════════════════════════════
# ANGKA YANG DIBACA LAYAR
# ══════════════════════════════════════════════════════════════════════════════
async def hpp_snapshot(db, material_id: str) -> dict:
    """HPP satu FG: WAC aktual (`wac_unit_cost`) + jejak lapisan batch (analitik:
    rata-rata lapisan bersisa, batch terakhir, rincian per SPK)."""
    res = {"material_id": material_id, "source": "none",
           "hpp_fifo_avg": 0.0, "hpp_last_batch": 0.0, "qty_on_layers": 0,
           "layer_count": 0, "open_layer_count": 0, "layers": [], "gaps": []}
    wac = await wac_state(db, material_id, init=False)
    res.update({"wac_unit_cost": wac["unit_cost"], "wac_components": wac["components"],
                "wac_source": wac["source"], "wac_initialized": wac["initialized"]})
    rows = await db[LAYERS].find({"material_id": material_id}, {"_id": 0}
                                 ).sort("created_at", -1).to_list(200)
    if not rows:
        return res
    res["layer_count"] = len(rows)
    res["hpp_last_batch"] = _r(rows[0].get("unit_cost"))
    open_rows = [r for r in rows if _f(r.get("qty_remaining")) > 0]
    res["open_layer_count"] = len(open_rows)
    qty = sum(_f(r.get("qty_remaining")) for r in open_rows)
    res["qty_on_layers"] = int(qty)
    if qty > 0:
        res["hpp_fifo_avg"] = _r(
            sum(_f(r.get("unit_cost")) * _f(r.get("qty_remaining")) for r in open_rows) / qty)
        res["source"] = "fifo_remaining"
    else:
        # semua lapisan habis — angka terakhir yang PERNAH nyata tetap berguna,
        # tetapi harus MENGAKU bahwa stoknya nol.
        res["hpp_fifo_avg"] = res["hpp_last_batch"]
        res["source"] = "fifo_last_batch_no_stock"
    res["layers"] = [{
        "id": r["id"], "qty_in": r.get("qty_in"), "qty_remaining": r.get("qty_remaining"),
        "unit_cost": _r(r.get("unit_cost")), "breakdown": r.get("breakdown") or {},
        "batch": r.get("batch") or {}, "gaps": r.get("gaps") or [],
        "created_at": (r.get("created_at").isoformat()
                       if isinstance(r.get("created_at"), datetime) else r.get("created_at")),
    } for r in rows[:50]]
    all_gaps = []
    for r in open_rows:
        for g in (r.get("gaps") or []):
            if g not in all_gaps:
                all_gaps.append(g)
    res["gaps"] = all_gaps
    return res
