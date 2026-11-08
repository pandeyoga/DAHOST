"""core.hpp_aktual — SATU hitungan HPP AKTUAL per PO (internal & maklon). Tahap 9, keputusan owner 7 Nov 2026.

RUMUS (keputusan No. 13 + rumus HPP aktual per PO)
--------------------------------------------------
    HPP aktual PO = potongan (nilai dari cutting, saat diserahkan) + aksesoris yang diserahkan
                  + upah CMT (tagihan nyata) + permak
    margin (maklon) = harga jasa − HPP
    margin terealisasi (maklon) = pendapatan (pcs dikirim ke klien × harga jasa) − biaya pcs yang dikirim itu
                                  (bahan per pcs dikirim ke CMT × pcs dikirim ke klien + upah CMT & permak pro-rata
                                  pcs dikirim ÷ pcs lolos QC) — dasar hitung pendapatan & biaya SEPADAN (8 Nov 2026)

* BOM hanya simulasi/standar (tab "HPP standar per potong"); angka di sini hanya dari data nyata.
* Upah internal dan biaya umum produksi (overhead) TIDAK masuk HPP (keputusan 6 Nov, No. 6). Biaya umum per pcs
  ditampilkan sebagai INFORMASI: beban akun berpenanda overhead produksi sebulan ÷ pcs lolos QC bulan itu
  (per CV: PO internal = buku CV Dewi Aditya, PO maklon = buku CV Sukma).
* Isian manual HPP maklon (komponen, overhead %, margin %) dihapus — dokumen lama tidak dibaca lagi.

SUMBER (semua dibaca, tidak ada koleksi baru)
---------------------------------------------
* Dokumen penyerahan `rahaza_material_issues` (satu per kiriman ke CMT). Kontrak baru:
  `po_id`, `shipment_id`, items[{material_id, qty_issued, unit_cost_applied, kind: potongan|aksesoris,
  po_item_id (potongan)}], maklon + `cost_target='maklon'`. Dokumen LAMA (`production_po_id`,
  `vendor_shipment_id`, tanpa `kind`/`po_item_id`) tetap dibaca: jenisnya dari master (potongan = master
  potongan `CUT-`/`is_cut_panel`, lainnya = aksesoris & bahan lain), baris PO-nya dari surat jalan.
* Pengeluaran Request Internal / Keluar manual ber-PO (kartu stok `po_id`), kecuali bahan pembantu.
* Bahan pembantu (benang dsb., keputusan No. 5): kategori material berpenanda `bahan_pembantu` (bawaan:
  kategori Benang Jahit). Langsung beban 5-3400 saat dikeluarkan — TIDAK pernah masuk HPP per PO.
* pcs dikirim per baris PO: `vendor_shipment_items.qty_sent` (kiriman batal & kiriman rework tidak dihitung);
  tanpa surat jalan sama sekali → qty pesanan.
* lolos QC: `core.dispatch_capacity.po_item_quantities` (SSOT angka qty).
* upah CMT: `dewi_cmt_payments` (bukan batal); permak: `dewi_cmt_permak.total_cost`.

LAPISAN BARANG JADI (Terima FG PO internal — `core.fg_cost_layers.compute_batch_unit_cost`)
----------------------------------------------------------------------------------------------
    bahan batch = potongan baris itu ÷ pcs baris itu yang dikirim × qty
                + aksesoris PO ÷ pcs PO yang dikirim × qty
dibatasi sisa nilai yang belum terserap lapisan sebelumnya — WIP tidak pernah dikredit melebihi yang didebit.
Bahan untuk pcs yang tidak pernah diterima (hilang/reject/sisa di CMT) tetap di WIP PO itu dan ditutup saat
PO ditutup sebagai selisih biaya PO (`core.po_wip.on_po_closed`, profil `production_po_wip_variance`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KIND_CUT = "potongan"
KIND_ACC = "aksesoris"
KIND_AUX = "bahan_pembantu"
KIND_LABELS = {KIND_CUT: "Potongan", KIND_ACC: "Aksesoris",
               KIND_AUX: "Bahan pembantu (beban produksi, tidak masuk HPP)"}
MATERIAL_BASIS = "aktual"
# Penanda SATU-SATUNYA bahan pembantu: field boolean di master kategori material.
AUX_FLAG = "bahan_pembantu"
AUX_DEFAULT_CATEGORY_CODES = ("SEWING_THREAD",)     # Benang Jahit — bawaan bila penanda belum diisi
CUT_PANEL_CATEGORY_CODES = ("CUT_PANEL",)
MI_NOT_COUNTED = ("rejected", "draft", "cancelled")
SHIP_NOT_COUNTED = ("cancelled", "void", "voided", "rejected")
CMT_BILL_VOID = ("cancelled", "void", "voided")
CLOSED_STATUSES = ("Closed", "Closed Short", "Completed")
PO_HIDDEN_STATUSES = ("Draft", "Cancelled", "Rejected")
COST_SOURCE_LABEL = {"issue": "nilai saat diserahkan", "master": "harga master (dokumen lama)",
                     "missing": "harga belum ada"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r(v, nd: int = 2) -> float:
    return round(_f(v), nd)


def _up(v) -> str:
    return str(v or "").strip().upper()


# ══════════════════════════════════════════════════════════════════════════════
# 1. BAHAN PEMBANTU (keputusan No. 5) — satu penanda di master kategori material
# ══════════════════════════════════════════════════════════════════════════════
def category_is_aux(cat: dict | None) -> bool:
    """Kategori bahan pembantu? Penanda `bahan_pembantu` di master menang; bila belum diisi, bawaan = Benang Jahit."""
    c = cat or {}
    if c.get(AUX_FLAG) is not None:
        return bool(c.get(AUX_FLAG))
    return _up(c.get("code")) in AUX_DEFAULT_CATEGORY_CODES


async def aux_category_keys(db) -> set:
    """Kunci pengenal kategori bahan pembantu: id, kode, dan `name:<nama>` (data lama menyimpan nama)."""
    out: set = set()
    async for c in db.rahaza_material_categories.find({}, {"_id": 0, "id": 1, "code": 1, "name": 1, AUX_FLAG: 1}):
        if category_is_aux(c):
            for k in (c.get("id"), _up(c.get("code"))):
                if k:
                    out.add(k)
            if c.get("name"):
                out.add("name:" + str(c["name"]).strip().lower())
    return out


def material_is_aux(mat: dict | None, aux_keys: set) -> bool:
    m = mat or {}
    if not m or (m.get("type") or "") == "fg" or not aux_keys:
        return False
    for k in (m.get("category_id"), m.get("category"), m.get("category_code")):
        if k and (k in aux_keys or _up(k) in aux_keys):
            return True
    name = str(m.get("category_name") or "").strip().lower()
    return bool(name) and ("name:" + name) in aux_keys


async def is_bahan_pembantu(db, mat: dict | None) -> bool:
    """Material ini bahan pembantu (benang dsb.)? Dipakai pengeluaran aksesoris & jurnal Material Issue."""
    if not mat:
        return False
    return material_is_aux(mat, await aux_category_keys(db))


# ══════════════════════════════════════════════════════════════════════════════
# 2. BARIS PENYERAHAN — jenis & nilai (fungsi murni)
# ══════════════════════════════════════════════════════════════════════════════
def _is_panel(mat: dict | None) -> bool:
    from core.cut_panel_master import is_panel_material
    m = mat or {}
    return is_panel_material(m) or _up(m.get("category_code")) in CUT_PANEL_CATEGORY_CODES


def line_kind(item: dict, mat: dict | None, aux_keys: set) -> str:
    """potongan | aksesoris | bahan_pembantu. `kind` dari dokumen baru dipakai; dokumen lama dari master.
    Bahan pembantu selalu menang (benang tidak pernah masuk HPP, walau ikut terkirim)."""
    if material_is_aux(mat, aux_keys):
        return KIND_AUX
    k = str((item or {}).get("kind") or "").strip().lower()
    if k in (KIND_CUT, KIND_ACC):
        return k
    return KIND_CUT if _is_panel(mat) else KIND_ACC


def line_value(item: dict, mat: dict | None) -> tuple:
    """(qty bersih, harga satuan, nilai, sumber harga). qty = diserahkan − diretur; harga = nilai saat diserahkan
    (`unit_cost_applied`, sama dengan jurnalnya), master hanya untuk dokumen lama tanpa nilai."""
    qty = max(0.0, _f((item or {}).get("qty_issued")) - _f((item or {}).get("qty_returned")))
    uc = _f((item or {}).get("unit_cost_applied"))
    src = "issue"
    if uc <= 0:
        uc = _f((mat or {}).get("unit_cost"))
        src = "master" if uc > 0 else "missing"
    return round(qty, 4), uc, round(qty * uc, 2), src


def _panel_matches(mat: dict, pi: dict) -> bool:
    """Master potongan (model × warna × ukuran) cocok dengan baris PO?"""
    if not mat.get("model_id") or mat.get("model_id") != pi.get("model_id"):
        return False
    sz = _up(mat.get("size_code"))
    psz = {_up(pi.get("size_code")), _up(pi.get("size"))} - {""}
    if sz and psz and sz not in psz:
        return False
    col = _up(mat.get("color_code"))
    pcol = {_up(pi.get("color_code")), _up(pi.get("color"))} - {""}
    if col and pcol and col not in pcol and _up(mat.get("color_name")) not in pcol:
        return False
    return True


def _cut_targets(item: dict, mat: dict, ship_lines: list, items_by_id: dict) -> list:
    """[(po_item_id, bobot)] untuk satu baris potongan. Dokumen baru menyebut `po_item_id`; dokumen lama
    dicocokkan ke baris surat jalan lewat master potongan, lalu (satu baris saja) ke baris itu."""
    pid = (item or {}).get("po_item_id")
    if pid and pid in items_by_id:
        return [(pid, 1.0)]
    lines = [ln for ln in (ship_lines or []) if ln.get("po_item_id") in items_by_id]
    cands = [ln for ln in lines if _panel_matches(mat or {}, items_by_id[ln["po_item_id"]])]
    if not cands and not lines:
        cands = [{"po_item_id": p, "qty_sent": 1} for p, pi in items_by_id.items() if _panel_matches(mat or {}, pi)]
    if not cands and len({ln["po_item_id"] for ln in lines}) == 1:
        cands = lines
    tot = sum(_f(c.get("qty_sent")) for c in cands)
    if not cands:
        return []
    if tot <= 0:
        return [(c["po_item_id"], 1.0 / len(cands)) for c in cands]
    agg: dict = {}
    for c in cands:
        agg[c["po_item_id"]] = agg.get(c["po_item_id"], 0.0) + _f(c.get("qty_sent")) / tot
    return list(agg.items())


def mi_po_id(mi: dict) -> str:
    return (mi or {}).get("po_id") or (mi or {}).get("production_po_id") or ""


def mi_shipment_id(mi: dict) -> str:
    return (mi or {}).get("shipment_id") or (mi or {}).get("vendor_shipment_id") or ""


def summarize_issues(*, items: list, mis: list, req_lines: list, ship_rows: list, mats: dict,
                     aux_keys: set) -> dict:
    """Ringkasan bahan yang DISERAHKAN untuk satu PO (fungsi murni).

    Return {cut: {po_item_id: nilai}, cut_qty, acc_value, aux_value, sent: {po_item_id: pcs}, sent_total,
    sent_basis ('kiriman'|'pesanan'), lines[], gaps[]}."""
    items_by_id = {i["id"]: i for i in items or [] if i.get("id")}
    sent = {pid: 0.0 for pid in items_by_id}
    by_ship: dict = {}
    for r in ship_rows or []:
        pid = r.get("po_item_id")
        if pid not in sent:
            continue
        sent[pid] += _f(r.get("qty_sent"))
        by_ship.setdefault(r.get("shipment_id") or "", []).append(r)
    basis = "kiriman"
    if sum(sent.values()) <= 0:
        basis = "pesanan"
        sent = {pid: _f(pi.get("qty")) for pid, pi in items_by_id.items()}
    cut = {pid: 0.0 for pid in items_by_id}
    cut_qty = {pid: 0.0 for pid in items_by_id}
    acc = aux = unmapped = 0.0
    lines, gaps, missing = [], [], []

    def _row(src_doc, src_label, it, mat, kind, qty, uc, val, csrc, pid=""):
        return {"doc": src_doc, "source": src_label, "material_id": it.get("material_id"),
                "material_code": (mat or {}).get("code") or it.get("material_code") or "",
                "material_name": (mat or {}).get("name") or it.get("material_name") or "",
                "unit": (mat or {}).get("unit") or it.get("unit") or "", "kind": kind,
                "kind_label": KIND_LABELS[kind], "qty": qty, "unit_cost": round(uc, 4), "value": val,
                "cost_source": csrc, "cost_source_label": COST_SOURCE_LABEL[csrc], "po_item_id": pid,
                "in_hpp": kind != KIND_AUX}

    for mi in mis or []:
        doc = mi.get("mi_number") or mi.get("id") or ""
        ship_lines = by_ship.get(mi_shipment_id(mi)) or []
        for it in mi.get("items") or []:
            mat = mats.get(it.get("material_id")) or {}
            kind = line_kind(it, mat, aux_keys)
            qty, uc, val, csrc = line_value(it, mat)
            if qty <= 0:
                continue
            if csrc == "missing":
                missing.append(mat.get("code") or it.get("material_id") or "?")
            pid = ""
            if kind == KIND_AUX:
                aux += val
            elif kind == KIND_CUT:
                targets = _cut_targets(it, mat, ship_lines, items_by_id)
                if targets:
                    for p, w in targets:
                        cut[p] += val * w
                        cut_qty[p] += qty * w
                    pid = targets[0][0] if len(targets) == 1 else ""
                else:
                    unmapped += val
            else:
                acc += val
            lines.append(_row(doc, "Kirim ke CMT", it, mat, kind, qty, uc, val, csrc, pid))
    for rl in req_lines or []:
        mat = mats.get(rl.get("material_id")) or {}
        kind = KIND_AUX if (material_is_aux(mat, aux_keys) or rl.get("cost_target") == KIND_AUX) else KIND_ACC
        qty = round(abs(_f(rl.get("qty"))), 4)
        uc = _f(rl.get("unit_cost")) or _f(mat.get("unit_cost"))
        val = round(_f(rl.get("value")) or qty * uc, 2)
        if qty <= 0 and val <= 0:
            continue
        if kind == KIND_AUX:
            aux += val
        else:
            acc += val
        lines.append(_row(rl.get("doc") or "", "Permintaan aksesoris", rl, mat, kind, qty, uc, val,
                          "issue" if uc > 0 else "missing"))
    sent_total = sum(sent.values())
    if unmapped > 0:
        # dokumen lama: potongan tanpa baris PO dibagi per pcs dikirim (tidak ditebak ke satu ukuran)
        for pid in cut:
            if sent_total > 0:
                cut[pid] += unmapped * sent[pid] / sent_total
        gaps.append(f"Potongan senilai Rp {unmapped:,.0f} dari dokumen lama tidak menyebut baris PO — "
                    "dibagi per pcs yang dikirim.".replace(",", "."))
    if missing:
        gaps.append("Harga belum ada untuk " + ", ".join(sorted(set(missing))[:6])
                    + " — nilai baris itu Rp 0 sampai harganya diisi.")
    if basis == "pesanan" and (sum(cut.values()) + acc) > 0:
        gaps.append("Belum ada surat jalan ke CMT — bahan dibagi per pcs pesanan.")
    return {"cut": {k: round(v, 2) for k, v in cut.items()}, "cut_qty": {k: round(v, 4) for k, v in cut_qty.items()},
            "cut_value": round(sum(cut.values()), 2), "acc_value": round(acc, 2), "aux_value": round(aux, 2),
            "sent": sent, "sent_total": sent_total, "sent_basis": basis, "lines": lines, "gaps": gaps,
            "has_issues": (sum(cut.values()) + acc) > 0}


# ══════════════════════════════════════════════════════════════════════════════
# 3. LAPISAN BARANG JADI — bagian bahan per batch (fungsi murni)
# ══════════════════════════════════════════════════════════════════════════════
def absorbed_from_layers(layers: list) -> dict:
    """Bahan & biaya yang SUDAH terserap lapisan barang jadi satu PO (lapisan produksi, bukan barang kembali)."""
    out = {"cut": {}, "acc": 0.0, "legacy": 0.0, "value": 0.0, "material": 0.0, "sewing": 0.0,
           "permak": 0.0, "qty": 0.0, "layers": 0}
    for ly in layers or []:
        bd = ly.get("breakdown") or {}
        if bd.get("source") == "returned_at_exit_cost" or not (ly.get("batch") or {}).get("po_item_id"):
            continue
        q = _f(ly.get("qty_in"))
        out["layers"] += 1
        out["qty"] += q
        out["value"] += _f(ly.get("total_cost"))
        out["sewing"] += _f(bd.get("sewing_cost")) * q
        out["permak"] += _f(bd.get("permak_cost")) * q
        if bd.get("material_basis") == MATERIAL_BASIS:
            pid = (ly.get("batch") or {}).get("po_item_id")
            out["cut"][pid] = out["cut"].get(pid, 0.0) + _f(bd.get("cut_value"))
            out["acc"] += _f(bd.get("accessory_value"))
            out["material"] += _f(bd.get("cut_value")) + _f(bd.get("accessory_value"))
        else:
            out["legacy"] += _f(bd.get("material_cost")) * q
            out["material"] += _f(bd.get("material_cost")) * q
    for k in ("acc", "legacy", "value", "material", "sewing", "permak"):
        out[k] = round(out[k], 2)
    return out


def allocate_batch(summary: dict, po_item_id: str, qty: float, absorbed: dict) -> dict:
    """Bahan untuk satu batch barang jadi: per pcs dikirim, dibatasi sisa yang belum terserap."""
    q = max(0.0, _f(qty))
    cut_v = _f((summary.get("cut") or {}).get(po_item_id))
    acc_v = _f(summary.get("acc_value"))
    sent_i = _f((summary.get("sent") or {}).get(po_item_id))
    sent_t = _f(summary.get("sent_total"))
    cut_pp = cut_v / sent_i if sent_i > 0 else 0.0
    acc_pp = acc_v / sent_t if sent_t > 0 else 0.0
    ab_cut = absorbed.get("cut") or {}
    cut_b = min(cut_pp * q, max(0.0, cut_v - _f(ab_cut.get(po_item_id))))
    acc_b = min(acc_pp * q, max(0.0, acc_v - _f(absorbed.get("acc"))))
    room = max(0.0, _f(summary.get("cut_value")) + acc_v - _f(absorbed.get("legacy"))
               - sum(_f(v) for v in ab_cut.values()) - _f(absorbed.get("acc")))
    capped = (cut_b + 1e-6 < cut_pp * q) or (acc_b + 1e-6 < acc_pp * q)
    if cut_b + acc_b > room + 1e-6:
        over = cut_b + acc_b - room
        take = min(acc_b, over)
        acc_b -= take
        cut_b = max(0.0, cut_b - (over - take))
        capped = True
    return {"cut_value": round(cut_b, 2), "accessory_value": round(acc_b, 2),
            "material_value": round(cut_b + acc_b, 2), "cut_per_pcs": round(cut_pp, 4),
            "accessory_per_pcs": round(acc_pp, 4), "sent_item": sent_i, "sent_total": sent_t,
            "sent_basis": summary.get("sent_basis") or "kiriman", "capped": capped}


# ══════════════════════════════════════════════════════════════════════════════
# 4. PEMUAT DATA (sekali per kumpulan PO)
# ══════════════════════════════════════════════════════════════════════════════
async def _load(db, po_ids: list) -> dict:
    """Semua dokumen yang dibutuhkan HPP aktual untuk kumpulan PO — sekali baca per koleksi."""
    po_ids = [p for p in dict.fromkeys(po_ids or []) if p]
    if not po_ids:
        return {"items": [], "mis": [], "req": [], "ship": [], "mats": {}, "aux": set(), "bills": [],
                "permak": [], "layers": [], "nota": [], "receipts": [], "jobs": {}}
    items = await db.po_items.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(20000)
    item_ids = [i["id"] for i in items if i.get("id")]
    jobs = {}
    async for j in db.production_jobs.find({"po_id": {"$in": po_ids}}, {"_id": 0, "id": 1, "po_id": 1}):
        jobs[j["id"]] = j.get("po_id")
    ors = [{"po_id": {"$in": po_ids}}, {"production_po_id": {"$in": po_ids}}]
    if jobs:
        ors.append({"job_id": {"$in": list(jobs)}})
    mis = await db.rahaza_material_issues.find(
        {"$or": ors, "status": {"$nin": list(MI_NOT_COUNTED)}}, {"_id": 0}).to_list(5000)
    for mi in mis:
        if not mi_po_id(mi) and mi.get("job_id") in jobs:
            mi["po_id"] = jobs[mi["job_id"]]
    req = []
    async for mv in db.rahaza_material_movements.find(
            {"po_id": {"$in": po_ids}, "movement_type": "issue"},
            {"_id": 0, "id": 1, "po_id": 1, "material_id": 1, "material_name": 1, "qty": 1, "qty_signed": 1,
             "unit_cost": 1, "cost_target": 1, "related_ref": 1, "reference_id": 1}):
        q = mv.get("qty_signed") if mv.get("qty_signed") is not None else mv.get("qty")
        req.append({"po_id": mv.get("po_id"), "material_id": mv.get("material_id"),
                    "material_name": mv.get("material_name") or "", "qty": abs(_f(q)),
                    "unit_cost": _f(mv.get("unit_cost")), "cost_target": mv.get("cost_target") or "",
                    "doc": mv.get("related_ref") or mv.get("reference_id") or ""})
    async for rq in db.dewi_accessory_requests.find(
            {"po_id": {"$in": po_ids}, "stock_issued": True, "issue_linked_po": {"$ne": True}},
            {"_id": 0, "po_id": 1, "request_code": 1, "stock_issue_results": 1, "cost_target": 1}):
        for r in rq.get("stock_issue_results") or []:
            req.append({"po_id": rq.get("po_id"), "material_id": r.get("material_id"),
                        "material_name": r.get("material_name") or "", "qty": _f(r.get("qty")),
                        "unit_cost": _f(r.get("unit_cost")), "value": _f(r.get("value")),
                        "cost_target": rq.get("cost_target") or "", "doc": rq.get("request_code") or ""})
    ship = await db.vendor_shipment_items.find(
        {"po_item_id": {"$in": item_ids}}, {"_id": 0, "shipment_id": 1, "po_item_id": 1, "qty_sent": 1}
    ).to_list(50000) if item_ids else []
    sids = list({s.get("shipment_id") for s in ship if s.get("shipment_id")})
    bad = set()
    if sids:
        async for s in db.vendor_shipments.find({"id": {"$in": sids}},
                                                {"_id": 0, "id": 1, "status": 1, "shipment_type": 1}):
            if (str(s.get("status") or "").lower() in SHIP_NOT_COUNTED
                    or _up(s.get("shipment_type")) == "REWORK"):
                bad.add(s["id"])
    ship = [s for s in ship if s.get("shipment_id") not in bad]
    mat_ids = list({it.get("material_id") for mi in mis for it in (mi.get("items") or []) if it.get("material_id")}
                   | {r.get("material_id") for r in req if r.get("material_id")})
    mats = {}
    if mat_ids:
        async for m in db.rahaza_materials.find({"id": {"$in": mat_ids}}, {"_id": 0}):
            mats[m["id"]] = m
    bills = [b async for b in db.dewi_cmt_payments.find({"po_id": {"$in": po_ids}}, {"_id": 0})
             if str(b.get("status") or "").lower() not in CMT_BILL_VOID]
    permak = await db.dewi_cmt_permak.find(
        {"$or": [{"po_id": {"$in": po_ids}}] + ([{"po_item_id": {"$in": item_ids}}] if item_ids else [])},
        {"_id": 0, "id": 1, "po_id": 1, "po_item_id": 1, "total_cost": 1, "cost_per_pcs": 1, "qty": 1,
         "status": 1}).to_list(5000)
    layers = await db.fg_cost_layers.find({"batch.po_id": {"$in": po_ids}}, {"_id": 0}).to_list(20000)
    nota = await db.rahaza_ar_invoices.find(
        {"po_id": {"$in": po_ids}, "ic_source_ref": {"$exists": True}, "status": {"$ne": "cancelled"}},
        {"_id": 0, "po_id": 1, "margin_amount": 1, "ic_source_ref": 1}).to_list(5000)
    receipts = await db.cmt_receipts.find(
        {"po_id": {"$in": po_ids}},
        {"_id": 0, "id": 1, "po_id": 1, "status": 1, "qc_completed_at": 1, "approved_at": 1, "total_actual": 1,
         "own_team_no_bill": 1, "receipt_code": 1}).to_list(5000)
    return {"items": items, "mis": mis, "req": req, "ship": ship, "mats": mats,
            "aux": await aux_category_keys(db), "bills": bills, "permak": permak, "layers": layers,
            "nota": nota, "receipts": receipts, "jobs": jobs}


def _for_po(data: dict, po_id: str) -> dict:
    items = [i for i in data["items"] if i.get("po_id") == po_id]
    ids = {i["id"] for i in items}
    return {
        "items": items,
        "mis": [m for m in data["mis"] if mi_po_id(m) == po_id],
        "req": [r for r in data["req"] if r.get("po_id") == po_id],
        "ship": [s for s in data["ship"] if s.get("po_item_id") in ids],
        "bills": [b for b in data["bills"] if b.get("po_id") == po_id],
        "permak": [p for p in data["permak"] if p.get("po_id") == po_id or p.get("po_item_id") in ids],
        "layers": [ly for ly in data["layers"] if (ly.get("batch") or {}).get("po_id") == po_id],
        "nota": [n for n in data["nota"] if n.get("po_id") == po_id],
        "receipts": [r for r in data["receipts"] if r.get("po_id") == po_id],
    }


async def po_issue_summary(db, po_id: str) -> dict:
    """Ringkasan bahan yang diserahkan untuk satu PO (dipakai lapisan barang jadi)."""
    data = await _load(db, [po_id])
    d = _for_po(data, po_id)
    return summarize_issues(items=d["items"], mis=d["mis"], req_lines=d["req"], ship_rows=d["ship"],
                            mats=data["mats"], aux_keys=data["aux"]) | {"_layers": d["layers"]}


async def layer_material_for(db, *, po_item: dict, qty: float) -> dict | None:
    """Bahan AKTUAL untuk satu batch barang jadi PO internal; None bila PO ini belum punya penyerahan bahan
    (pemanggil lalu memakai BOM standar dan menyebutnya)."""
    po_id = (po_item or {}).get("po_id")
    if not po_id or not (po_item or {}).get("id"):
        return None
    s = await po_issue_summary(db, po_id)
    if not s.get("has_issues"):
        return None
    a = allocate_batch(s, po_item["id"], qty, absorbed_from_layers(s.get("_layers") or []))
    a["gaps"] = list(s.get("gaps") or [])
    if a["capped"]:
        a["gaps"].append("Nilai bahan batch ini dibatasi sisa bahan PO yang belum masuk barang jadi "
                         "(qty diterima melebihi bagian pcs yang dikirim).")
    if _f((s.get("cut") or {}).get(po_item["id"])) <= 0:
        a["gaps"].append("Belum ada potongan yang diserahkan untuk baris PO ini — nilai potongan batch Rp 0.")
    return a


# ══════════════════════════════════════════════════════════════════════════════
# 5. BIAYA UMUM PER PCS — informasi, TIDAK masuk HPP (keputusan No. 6)
# ══════════════════════════════════════════════════════════════════════════════
def _month_bounds(ym: str) -> tuple:
    y, m = (int(x) for x in ym.split("-")[:2])
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    return start, end


def _ym_of(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m")
    s = str(v or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else ""


async def overhead_accounts(db) -> list:
    """Akun beban berpenanda overhead produksi (`flags.is_cogs_overhead`), mis. 5-3100…5-3500."""
    rows = []
    async for a in db.rahaza_coa_accounts.find(
            {"$or": [{"flags.is_cogs_overhead": True}, {"is_cogs_overhead": True}]},
            {"_id": 0, "code": 1, "name": 1, "is_group": 1}):
        if not a.get("is_group") and a.get("code"):
            rows.append({"code": a["code"], "name": a.get("name") or ""})
    return sorted(rows, key=lambda r: r["code"])


async def overhead_month(db, ym: str, business_type: str = "internal", *, accounts: list | None = None) -> dict:
    """Biaya umum produksi satu bulan ÷ pcs lolos QC bulan itu (satu CV). Informasi saja."""
    from core.cmt_receipt_status import is_done
    from core.entities import DA, SMU, entity_match
    bt = "maklon" if business_type == "maklon" else "internal"
    ent = SMU if bt == "maklon" else DA
    accs = accounts if accounts is not None else await overhead_accounts(db)
    codes = [a["code"] for a in accs]
    start, end = _month_bounds(ym)
    by_code: dict = {}
    if codes:
        q = {"account_code": {"$in": codes}, "date": {"$gte": start.strftime("%Y-%m-%d"),
                                                      "$lt": end.strftime("%Y-%m-%d")}, **entity_match(ent)}
        async for ln in db.rahaza_journal_lines.find(q, {"_id": 0, "account_code": 1, "debit": 1, "credit": 1}):
            by_code[ln["account_code"]] = by_code.get(ln["account_code"], 0.0) + _f(ln.get("debit")) - _f(ln.get("credit"))
    total = round(sum(by_code.values()), 2)
    pcs = 0.0
    rcs = await db.cmt_receipts.find({"qc_completed_at": {"$gte": start, "$lt": end}},
                                     {"_id": 0, "po_id": 1, "status": 1, "total_actual": 1}).to_list(20000)
    po_ids = list({r.get("po_id") for r in rcs if r.get("po_id")})
    bts = {}
    if po_ids:
        async for p in db.production_pos.find({"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "business_type": 1}):
            bts[p["id"]] = "maklon" if (p.get("business_type") or "") == "maklon" else "internal"
    for r in rcs:
        if is_done(r.get("status")) and bts.get(r.get("po_id"), "internal") == bt:
            pcs += _f(r.get("total_actual"))
    names = {a["code"]: a["name"] for a in accs}
    return {"month": ym, "business_type": bt, "entity": ent, "overhead": total, "pcs": int(pcs),
            # tanpa beban tercatat (mis. buku CV Sukma belum diisi) = "belum ada data", bukan Rp 0 per pcs
            "per_pcs": round(total / pcs, 2) if (pcs > 0 and abs(total) >= 0.01) else None,
            "accounts": [{"code": c, "name": names.get(c, ""), "amount": round(v, 2)}
                         for c, v in sorted(by_code.items()) if abs(v) >= 0.01],
            "in_hpp": False}


# ══════════════════════════════════════════════════════════════════════════════
# 6. HPP PER PO — satu hitungan untuk PO internal & maklon
# ══════════════════════════════════════════════════════════════════════════════
def po_hpp_figures(*, po: dict, items: list, summary: dict, qmap: dict, bills: list, permak: list,
                   layers: list, nota: list, receipts: list) -> dict:
    """Angka HPP aktual satu PO (fungsi murni; `qmap` = core.dispatch_capacity.po_item_quantities)."""
    from core.cmt_receipt_status import is_done
    maklon = (po.get("business_type") or "") == "maklon"
    absorbed = absorbed_from_layers(layers)
    acc_margin = round(sum(_f(n.get("margin_amount")) for n in nota or []), 2) if maklon else 0.0
    rows, tot = [], {"ordered": 0.0, "sent": 0.0, "accepted": 0.0, "plan_wage": 0.0, "revenue": 0.0,
                     "price_x_qty": 0.0}
    sent_t = _f(summary.get("sent_total"))
    acc_v = _f(summary.get("acc_value")) + acc_margin
    missing_rate = 0
    for it in items:
        pid = it["id"]
        q = qmap.get(pid) or {}
        ordered = _f(it.get("qty"))
        accepted = _f(q.get("accepted_total"))
        sent = _f((summary.get("sent") or {}).get(pid))
        rate = _f(it.get("cmt_price_snapshot"))
        price = _f(it.get("selling_price_snapshot")) if maklon else 0.0
        cut_v = _f((summary.get("cut") or {}).get(pid))
        acc_share = acc_v * sent / sent_t if sent_t > 0 else 0.0
        if rate <= 0 and ordered > 0:
            missing_rate += 1
        revenue = (_f(q.get("dispatched")) * price) if maklon and (q.get("shipped") or q.get("dispatched")) else 0.0
        tot["ordered"] += ordered
        tot["sent"] += sent
        tot["accepted"] += accepted
        tot["plan_wage"] += rate * ordered
        tot["revenue"] += revenue
        tot["price_x_qty"] += price * ordered
        rows.append({
            "po_item_id": pid, "sku": it.get("sku") or "", "product_name": it.get("product_name") or "",
            "size": it.get("size") or "", "color": it.get("color") or "",
            "qty_ordered": int(ordered), "qty_sent": round(sent, 2), "qty_accepted": int(accepted),
            "qty_dispatched": int(_f(q.get("dispatched"))),
            "cmt_rate": round(rate, 2), "selling_price": round(price, 2),
            "cut_value": round(cut_v, 2), "accessory_value": round(acc_share, 2),
            "cut_per_pcs": round(cut_v / sent, 2) if sent > 0 else None,
            "accessory_per_pcs": round(acc_v / sent_t, 2) if sent_t > 0 else None,
            "material_per_pcs": (round(cut_v / sent + acc_v / sent_t, 2) if sent > 0 and sent_t > 0 else None),
            "revenue": round(revenue, 2),
        })
    cut_total = _f(summary.get("cut_value"))
    cmt_cost = round(sum(_f(b.get("subtotal", b.get("net_amount"))) for b in bills or []), 2)
    cmt_pcs = int(sum(_f(b.get("total_pcs")) for b in bills or []))
    permak_cost = 0.0
    for p in permak or []:
        permak_cost += _f(p.get("total_cost")) or _f(p.get("cost_per_pcs")) * _f(p.get("qty"))
    permak_cost = round(permak_cost, 2)
    total = round(cut_total + acc_v + cmt_cost + permak_cost, 2)
    accepted_t = tot["accepted"]
    # Bagian pcs lolos QC (menjadi barang jadi / diserahkan ke klien) = bahan per pcs DIKIRIM × pcs lolos QC
    # + upah CMT + permak — rumus yang SAMA dengan lapisan barang jadi PO internal. Sisanya (bahan untuk pcs
    # hilang/reject/sisa di CMT) = selisih biaya PO: tetap biaya PO (total & margin), ditutup saat PO ditutup.
    cut_absorbed = sum(min(r["cut_value"], (r["cut_per_pcs"] or 0) * r["qty_accepted"]) for r in rows)
    acc_absorbed = min(acc_v, (acc_v / sent_t * accepted_t) if sent_t > 0 else 0.0)
    mat_absorbed = cut_absorbed + acc_absorbed
    absorbed_cost = round(mat_absorbed + cmt_cost + permak_cost, 2)
    hpp_pcs = round(absorbed_cost / accepted_t, 2) if accepted_t > 0 else None
    hpp_pcs_all_in = round(total / accepted_t, 2) if accepted_t > 0 else None
    own_team = any(r.get("own_team_no_bill") for r in receipts or [])
    done_receipts = [r for r in receipts or [] if is_done(r.get("status"))]
    gaps = list(summary.get("gaps") or [])
    if accepted_t > 0 and not bills and not own_team:
        gaps.append("Belum ada tagihan CMT untuk pcs yang sudah lolos QC — upah CMT belum masuk HPP.")
    if own_team:
        gaps.append("Dijahit tim CV Sukma sendiri — tidak ada tagihan jahit; biaya tim dicatat lewat jurnal gaji.")
    if missing_rate:
        gaps.append(f"{missing_rate} baris PO belum punya tarif jahit — isi di form PO (kolom upah jahit).")
    if not summary.get("has_issues") and _f(tot["sent"]) > 0:
        gaps.append("Belum ada bahan yang tercatat diserahkan untuk kiriman PO ini.")
    price_avg = round(tot["price_x_qty"] / tot["ordered"], 2) if maklon and tot["ordered"] > 0 else None
    # 8 Nov 2026 (keputusan owner): MARGIN TEREALISASI. Pendapatan hanya dari pcs yang sudah dikirim ke klien,
    # sedangkan total HPP memuat bahan untuk SEMUA pcs yang sudah dikirim ke CMT — selama PO berjalan margin
    # "pendapatan − total HPP" tampak kecil/minus. Dasar sepadan: biaya dialokasikan pro-rata ke pcs terkirim.
    # Hanya tampilan/laporan — angka ini TIDAK dipakai jurnal mana pun.
    disp_t = sum(r["qty_dispatched"] for r in rows)
    cut_shipped = sum(min(r["cut_value"], (r["cut_per_pcs"] or 0) * r["qty_dispatched"]) for r in rows)
    acc_shipped = min(acc_v, (acc_v / sent_t * disp_t) if sent_t > 0 else 0.0)
    labor_ratio = (min(1.0, disp_t / accepted_t) if accepted_t > 0 else (1.0 if disp_t > 0 else 0.0))
    realized_cost = round(cut_shipped + acc_shipped + (cmt_cost + permak_cost) * labor_ratio, 2) if maklon else None
    margin_pcs = round(price_avg - hpp_pcs, 2) if (price_avg is not None and hpp_pcs is not None) else None
    revenue = round(tot["revenue"], 2)
    months: dict = {}
    for r in done_receipts:
        ym = _ym_of(r.get("qc_completed_at") or r.get("approved_at"))
        if ym:
            months[ym] = months.get(ym, 0.0) + _f(r.get("total_actual"))
    return {
        "po_id": po.get("id"), "po_number": po.get("po_number") or "", "status": po.get("status") or "",
        "business_type": "maklon" if maklon else "internal",
        "vendor_name": po.get("vendor_name") or "", "client_name": po.get("customer_name") or po.get("client_name") or "",
        "client_id": po.get("buyer_id") or po.get("client_id") or "", "vendor_id": po.get("vendor_id") or "",
        "po_date": po.get("po_date") or "",
        "closed": po.get("status") in CLOSED_STATUSES,
        "qty_ordered": int(tot["ordered"]), "qty_sent": round(tot["sent"], 2), "qty_accepted": int(accepted_t),
        "qty_dispatched": int(sum(r["qty_dispatched"] for r in rows)),
        "sent_basis": summary.get("sent_basis") or "kiriman",
        "cut_cost": round(cut_total, 2), "accessory_cost": round(acc_v, 2),
        "accessory_margin_ic": acc_margin,
        "cmt_cost": cmt_cost, "cmt_pcs_billed": cmt_pcs, "cmt_cost_plan": round(tot["plan_wage"], 2),
        "permak_cost": permak_cost, "total_hpp": total, "hpp_per_pcs": hpp_pcs, "hpp_per_pcs_all_in": hpp_pcs_all_in,
        "absorbed_cost": absorbed_cost, "unabsorbed_cost": round(total - absorbed_cost, 2),
        "fg_layer_value": round(absorbed["value"], 2) if not maklon else 0.0,
        "aux_cost_excluded": _f(summary.get("aux_value")),
        "selling_price_per_pcs": price_avg, "margin_per_pcs": margin_pcs,
        "margin_pct": (round(margin_pcs / price_avg * 100, 2) if (margin_pcs is not None and price_avg) else None),
        "revenue": revenue, "margin": (round(revenue - total, 2) if maklon else None),
        # margin terealisasi (dasar sepadan) — lihat catatan di atas; `margin` = pendapatan − total biaya s.d. kini
        "realized_cost": realized_cost,
        "margin_realized": (round(revenue - realized_cost, 2) if maklon else None),
        "margin_realized_pct": (round((revenue - realized_cost) / revenue * 100, 2) if (maklon and revenue) else None),
        "cost_not_shipped": (round(total - realized_cost, 2) if maklon else None),
        "items_missing_rate": missing_rate, "own_team": own_team,
        "receipt_months": {k: int(v) for k, v in sorted(months.items())},
        "lines": rows, "issue_lines": summary.get("lines") or [], "gaps": gaps,
        # `per_pcs` = bagian pcs lolos QC ÷ pcs lolos QC → Σ per_pcs = HPP per pcs (bahan per pcs DIKIRIM)
        "components": [
            {"key": "potongan", "label": "Potongan (nilai dari cutting)", "amount": round(cut_total, 2),
             "absorbed": round(cut_absorbed, 2), "per_pcs": _pp(cut_absorbed, accepted_t)},
            {"key": "aksesoris", "label": "Aksesoris yang diserahkan", "amount": round(acc_v, 2),
             "absorbed": round(acc_absorbed, 2), "per_pcs": _pp(acc_absorbed, accepted_t)},
            {"key": "upah_cmt", "label": "Upah CMT (tagihan)", "amount": cmt_cost, "absorbed": cmt_cost,
             "per_pcs": _pp(cmt_cost, accepted_t)},
            {"key": "permak", "label": "Permak", "amount": permak_cost, "absorbed": permak_cost,
             "per_pcs": _pp(permak_cost, accepted_t)},
        ],
    }


def _pp(v, pcs) -> float | None:
    return round(_f(v) / pcs, 2) if pcs and pcs > 0 else None


async def po_hpp_many(db, pos: list, *, with_overhead: bool = True) -> list:
    """HPP aktual untuk banyak PO sekaligus (satu kali baca per koleksi)."""
    from core import dispatch_capacity as dcap
    pos = [p for p in pos or [] if p and p.get("id")]
    if not pos:
        return []
    data = await _load(db, [p["id"] for p in pos])
    qmap = await dcap.po_item_quantities(db, [i["id"] for i in data["items"] if i.get("id")])
    accs = await overhead_accounts(db) if with_overhead else []
    oh_cache: dict = {}
    out = []
    for po in pos:
        d = _for_po(data, po["id"])
        s = summarize_issues(items=d["items"], mis=d["mis"], req_lines=d["req"], ship_rows=d["ship"],
                             mats=data["mats"], aux_keys=data["aux"])
        fig = po_hpp_figures(po=po, items=d["items"], summary=s, qmap=qmap, bills=d["bills"],
                             permak=d["permak"], layers=d["layers"], nota=d["nota"], receipts=d["receipts"])
        if with_overhead:
            fig["overhead_info"] = await _po_overhead(db, fig, accs, oh_cache)
        out.append(fig)
    return out


async def _po_overhead(db, fig: dict, accs: list, cache: dict) -> dict:
    """Biaya umum per pcs untuk PO ini = rata-rata tertimbang bulan-bulan barangnya lolos QC."""
    months = fig.get("receipt_months") or {}
    bt = fig.get("business_type") or "internal"
    rows, pcs_t, val = [], 0.0, 0.0
    for ym, pcs in months.items():
        key = (ym, bt)
        if key not in cache:
            cache[key] = await overhead_month(db, ym, bt, accounts=accs)
        m = cache[key]
        rows.append({"month": ym, "pcs_po": pcs, "per_pcs": m["per_pcs"], "overhead": m["overhead"], "pcs": m["pcs"]})
        if m["per_pcs"] is not None:
            pcs_t += pcs
            val += pcs * m["per_pcs"]
    return {"per_pcs": round(val / pcs_t, 2) if pcs_t > 0 else None, "months": rows, "in_hpp": False,
            "note": "Informasi saja — biaya umum produksi tidak masuk HPP (keputusan 6 Nov 2026)."}


async def po_hpp(db, po_id: str, *, detail: bool = True) -> dict | None:
    """HPP aktual satu PO + (detail) HPP standar per baris dan posisi WIP PO internal."""
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        return None
    rows = await po_hpp_many(db, [po])
    fig = rows[0]
    if not detail:
        return fig
    if fig["business_type"] == "internal":
        from core import fg_cost_layers as fcl
        from core import product_costing as pc
        items = {i["id"]: i async for i in db.po_items.find({"po_id": po_id}, {"_id": 0})}
        for ln in fig["lines"]:
            it = items.get(ln["po_item_id"]) or {}
            try:
                with pc.bom_color_scope(pc.color_of(it)):
                    std = await fcl.compute_batch_unit_cost(db, po_item=it, qty=max(1, ln["qty_ordered"] or 1),
                                                            basis="standard")
                ln["standard_per_pcs"] = std["unit_cost"]
                ln["standard_material_per_pcs"] = std["material_cost"]
            except Exception:  # noqa: BLE001 — pembanding saja; tidak boleh menggagalkan HPP aktual
                log.exception("HPP standar baris %s gagal", ln.get("po_item_id"))
                ln["standard_per_pcs"] = None
                ln["standard_material_per_pcs"] = None
        try:
            from core import po_wip
            fig["wip"] = await po_wip.po_wip_position(db, po_id)
        except Exception:  # noqa: BLE001
            log.exception("posisi WIP PO %s gagal", po.get("po_number"))
            fig["wip"] = None
    return fig


def close_residue_note(fig: dict | None) -> str:
    """Kalimat jurnal penutup: kenapa masih ada sisa biaya PO (dipakai `core.po_wip.on_po_closed`)."""
    if not fig:
        return ""
    sent, acc = _f(fig.get("qty_sent")), _f(fig.get("qty_accepted"))
    parts = []
    if sent > acc:
        parts.append(f"bahan untuk {sent - acc:g} pcs dikirim yang tidak lolos QC/tidak diterima")
    if _f(fig.get("unabsorbed_cost")) and not parts:
        parts.append("sisa bahan yang belum masuk barang jadi")
    return ("; ".join(parts))[:120]
