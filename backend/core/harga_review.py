"""harga_review — REVIEW_HARGA_MATERIAL_DA.xlsx: SEMUA aksesoris & kain beserta harga, satuan, isi kemasan, pemakaian di BOM,
dan biaya per pcs yang ditimbulkannya — supaya owner bisa menemukan salah input harga (mis. harga per roll ditulis per meter)
yang membengkakkan HPP. Sheet MATERIAL memakai kolom importir (MAT_COLS) → berkas ini bisa langsung diunggah balik
ke layar Impor Harga · Rekening · BOM ("Terapkan semua sheet"); kolom tambahan di kanan diabaikan importir.
"""
from __future__ import annotations

import io
from collections import defaultdict

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from core.bom_uom import PACKAGING_UNITS, norm_unit
from core.master_fill import MAT_COLS, _head

RED = PatternFill("solid", fgColor="F8CBAD")      # sangat mencurigakan
YELLOW = PatternFill("solid", fgColor="FFF2CC")   # perlu dicek / isi
BLUE = PatternFill("solid", fgColor="DDEBF7")     # informasi dari sistem
WRAP = Alignment(wrap_text=True, vertical="top")
BOLD = Font(bold=True)

REVIEW_COLS = MAT_COLS + ["harga_per_pcs_atau_m_sekarang", "dipakai_di_model", "dipakai_di_bom", "qty_rata_per_pcs", "biaya_per_pcs_maks",
                          "model_biaya_maks", "porsi_hpp_maks_%", "tingkat", "kenapa_dicurigai"]
HPP_COLS = ["kode_model", "nama_model", "varian_bom", "hpp_per_pcs_bom_ini", "biaya_kain", "biaya_aksesoris", "porsi_aksesoris_%", "harga_jual",
            "baris_termahal", "biaya_baris_termahal", "tingkat", "catatan"]
LINE_COLS = ["kode_model", "nama_model", "varian_bom", "kode_material", "nama_material", "qty", "satuan", "qty_satuan_dasar", "satuan_dasar",
             "harga_per_satuan_dasar", "biaya_per_pcs", "porsi_hpp_%", "tingkat"]

ACC_LINE_RED, ACC_LINE_YELLOW = 15000.0, 5000.0          # biaya satu baris aksesoris per pcs
FAB_KG = (10000.0, 120000.0)                            # harga kain per kg yang wajar
FAB_YARD = (5000.0, 60000.0)                            # harga kain per yard yang wajar
CUT_QTY_MAX = {"kg": 1.5, "yard": 3.0, "m": 3.0}         # pemakaian kain per pcs yang wajar

PETUNJUK = [
    ("REVIEW HARGA MATERIAL — semua aksesoris & kain, pemakaian di BOM, dan dampaknya ke HPP", True),
    ("Tujuan: menemukan salah input harga yang membengkakkan HPP (mis. harga 1 ROLL ditulis sebagai harga 1 METER, atau isi kemasan belum diisi).", False),
    ("", False),
    ("WARNA BARIS", True),
    ("  MERAH  = sangat mencurigakan — biaya satu bahan ≥ Rp 15.000 per pcs produk, atau harga kain di luar kisaran wajar. Prioritas dicek.", False),
    ("  KUNING = perlu dicek — biaya per pcs Rp 5.000–15.000, harga kosong, atau isi kemasan (1 roll/pack/gross = berapa pcs/meter) belum diketahui.", False),
    ("  Tanpa warna = terlihat wajar. Tetap boleh dikoreksi.", False),
    ("", False),
    ("CARA MEMPERBAIKI (sheet MATERIAL — hanya 3 kolom yang dibaca sistem)", True),
    ("  1. 'satuan_beli'          = satuan yang tertulis di nota beli (roll / pack / gross / kg / yard / m / pcs).", False),
    ("  2. 'isi_per_satuan_beli'  = isi 1 satuan beli dalam satuan dasar (contoh: 1 roll bisban = 20 m → tulis 20; 1 gross kancing = 144 pcs → 144).", False),
    ("     Bila satuan_beli = satuan_dasar (mis. keduanya 'roll') dan isi > 1 → isi dibaca sebagai 'pcs per roll' dan harga = harga 1 roll.", False),
    ("  3. 'harga_per_satuan_beli' = harga 1 satuan beli (harga 1 roll / 1 gross / 1 kg / 1 yard). KOSONGKAN bila harga sudah benar → baris tidak diubah.", False),
    ("  Sistem menghitung sendiri harga per satuan dasar, memperbarui semua BOM yang memakai bahan itu, dan menghitung ulang HPP model.", False),
    ("", False),
    ("KOLOM BANTU (kanan, tidak dibaca importir)", True),
    ("  'harga_per_pcs_atau_m_sekarang' = harga per 1 pcs/1 m menurut sistem sekarang (harga kemasan ÷ isi). Ini yang benar-benar dipakai HPP.", False),
    ("  'qty_rata_per_pcs' = rata-rata pemakaian bahan per 1 pcs produk (satuan dasar). 'biaya_per_pcs_maks' = biaya terbesar yang ditimbulkan bahan ini", False),
    ("  pada satu produk, 'model_biaya_maks' = model mana, 'porsi_hpp_maks_%' = berapa persen HPP model itu berasal dari bahan ini.", False),
    ("", False),
    ("SHEET LAIN", True),
    ("  HPP_MODEL      = HPP per model (BOM varian pertama): kain vs aksesoris, baris termahal. Merah bila aksesoris > 50% HPP atau HPP > Rp 150.000.", False),
    ("  BOM_BARIS_MAHAL = 200 baris BOM dengan biaya per pcs terbesar — di sini biasanya salah input terlihat langsung.", False),
    ("  KAIN_PER_MODEL  = pemakaian kain (kg/yard) per potongan model & biayanya — cek qty yang tidak wajar.", False),
    ("", False),
    ("UNGGAH BALIK: Portal Keuangan → Akuntansi → Master Akuntansi → Impor Harga · Rekening · BOM → pilih berkas → 'Terapkan semua sheet'.", True),
]


def _widths(ws, widths):
    for i, w in enumerate(widths):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w


def _acc(ln: dict) -> bool:
    return (ln.get("material_type") or ln.get("type")) == "accessory" and not ln.get("is_cut_panel")


def _line_cost(ln: dict, mat: dict | None) -> float:
    qty_base = float(ln.get("qty_base") or 0)
    cost = float(ln.get("unit_cost_base") or 0)
    if cost <= 0 and mat:  # baris BOM lama tanpa harga tersimpan → pakai harga master
        cost = float(mat.get("unit_cost") or 0)
    return round(qty_base * cost, 2)


def _per_piece(mat: dict) -> float | None:
    """Harga per 1 pcs / 1 m menurut sistem: harga kemasan ÷ isi kemasan (bila satuan dasar = kemasan)."""
    cost = float(mat.get("unit_cost") or 0)
    if norm_unit(mat.get("unit") or "") in PACKAGING_UNITS:
        n = float(mat.get("pack_size") or 0)
        return round(cost / n, 2) if n > 1 else None
    return cost


def _flag_material(mat: dict, use: dict) -> tuple[str, str]:
    """→ (tingkat: MERAH/KUNING/'' , alasan)."""
    unit = norm_unit(mat.get("unit") or "")
    cost = float(mat.get("unit_cost") or 0)
    reasons, level = [], ""

    def mark(lv, txt):
        nonlocal level
        reasons.append(txt)
        if lv == "MERAH" or (lv == "KUNING" and level != "MERAH"):
            level = lv

    if cost <= 0:
        mark("KUNING", "harga masih 0 — isi harga_per_satuan_beli")
    if mat.get("type") == "fabric":
        lo, hi = FAB_KG if unit == "kg" else FAB_YARD if unit == "yard" else (0, 1e18)
        if cost > 0 and (cost < lo or cost > hi):
            mark("MERAH", f"harga kain Rp {cost:,.0f}/{unit} di luar kisaran wajar Rp {lo:,.0f}–{hi:,.0f}")
        if use["max_qty"] > CUT_QTY_MAX.get(unit, 1e9):
            mark("MERAH", f"pemakaian {use['max_qty']:g} {unit} per pcs di {use['max_model']} tidak wajar")
    else:
        if unit in PACKAGING_UNITS and float(mat.get("pack_size") or 0) <= 1:
            mark("KUNING", f"isi kemasan belum diisi (1 {unit} = berapa pcs/m?) → harga {unit} dianggap harga 1 pcs")
        if use["max_cost"] >= ACC_LINE_RED:
            mark("MERAH", f"bahan ini membebani Rp {use['max_cost']:,.0f} per pcs di {use['max_model']} — cek: harga ditulis per {unit}, "
                          f"padahal mungkin harga 1 roll/gross/pack; atau isi kemasan belum diisi")
        elif use["max_cost"] >= ACC_LINE_YELLOW:
            mark("KUNING", f"bahan ini membebani Rp {use['max_cost']:,.0f} per pcs di {use['max_model']} — pastikan harga & isi kemasan benar")
        if unit in ("m", "pcs") and cost > 50000:
            mark("MERAH", f"harga Rp {cost:,.0f} per {unit} sangat tinggi untuk aksesoris — kemungkinan harga per roll/gross")
    if use["max_share"] >= 50 and use["max_cost"] > 0 and mat.get("type") != "fabric":
        mark("MERAH", f"{use['max_share']:.0f}% HPP {use['max_model']} berasal dari bahan ini")
    return level, "; ".join(reasons)


async def build_harga_review(db) -> tuple[bytes, dict]:
    mats = {m["code"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}}, {"_id": 0}).to_list(50000)}
    models = {m["id"]: m for m in await db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0}).to_list(5000)}
    boms = await db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True, "model_id": {"$in": list(models)}}, {"_id": 0}).to_list(50000)
    boms.sort(key=lambda b: (models[b["model_id"]]["code"], b.get("color_code") or "", b.get("size_id") or ""))

    # ── pemakaian per material + biaya per BOM ──
    use = defaultdict(lambda: {"models": set(), "boms": 0, "qty_sum": 0.0, "max_cost": 0.0, "max_model": "", "max_share": 0.0, "max_qty": 0.0})
    bom_rows, line_rows, cut_rows = [], [], []
    for b in boms:
        m = models[b["model_id"]]
        label = f"{b.get('color') or b.get('color_code') or ''}".strip()
        lines = b.get("materials") or []
        costs = [(_line_cost(ln, mats.get(ln.get("code"))), ln) for ln in lines]
        total = round(sum(c for c, _ in costs), 2)
        fab = round(sum(c for c, ln in costs if not _acc(ln)), 2)
        acc = round(total - fab, 2)
        for c, ln in costs:
            code = ln.get("code") or ""
            share = round(100 * c / total, 1) if total > 0 else 0.0
            src = mats.get(code) or {}
            if ln.get("is_cut_panel"):
                fcode = ln.get("source_material_code") or (src.get("standard_cost_basis") or {}).get("fabric_code") or src.get("source_material_code")
                basis = src.get("standard_cost_basis") or {}
                fqty = float(basis.get("qty") or (ln.get("migrated_from_fabric") or {}).get("qty") or 0)
                fmat = mats.get(fcode) or {}
                if fcode:
                    u = use[fcode]
                    u["models"].add(m["code"]); u["boms"] += 1; u["qty_sum"] += fqty
                    if c > u["max_cost"]:
                        u["max_cost"], u["max_model"], u["max_share"] = c, m["code"], share
                    u["max_qty"] = max(u["max_qty"], fqty)
                cut_rows.append([m["code"], m["name"], label, fcode, fmat.get("name") or "", fqty, fmat.get("unit") or "", float(fmat.get("unit_cost") or 0), c, share])
                continue
            u = use[code]
            u["models"].add(m["code"]); u["boms"] += 1; u["qty_sum"] += float(ln.get("qty_base") or 0)
            if c > u["max_cost"]:
                u["max_cost"], u["max_model"], u["max_share"] = c, m["code"], share
            lvl = "MERAH" if c >= ACC_LINE_RED else "KUNING" if c >= ACC_LINE_YELLOW else ""
            line_rows.append([m["code"], m["name"], label, code, ln.get("name") or "", float(ln.get("qty") or 0), ln.get("unit") or "",
                              float(ln.get("qty_base") or 0), ln.get("unit_base") or "", float(ln.get("unit_cost_base") or src.get("unit_cost") or 0), c, share, lvl])
        top = max(costs, key=lambda x: x[0]) if costs else (0.0, {})
        share_acc = round(100 * acc / total, 1) if total > 0 else 0.0
        lvl, note = "", ""
        if total > 150000:
            lvl, note = "MERAH", f"HPP Rp {total:,.0f} sangat tinggi"
        if share_acc > 50:
            lvl, note = "MERAH", (note + "; " if note else "") + f"aksesoris {share_acc:.0f}% dari HPP (biasanya < 30%)"
        elif acc > 20000 and lvl != "MERAH":
            lvl, note = "KUNING", f"aksesoris Rp {acc:,.0f} per pcs — cek baris termahal"
        bom_rows.append([m["code"], m["name"], label, total, fab, acc, share_acc, float(m.get("retail_price") or 0),
                         f"{top[1].get('code') or ''} {top[1].get('name') or ''}".strip(), top[0], lvl, note])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PETUNJUK"
    for text, bold in PETUNJUK:
        ws.append([text])
        if bold:
            ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.column_dimensions["A"].width = 150

    # ── MATERIAL (importable) ──
    ws = wb.create_sheet("MATERIAL")
    _head(ws, REVIEW_COLS)
    stats = {"material": 0, "merah": 0, "kuning": 0, "aksesoris": 0, "kain": 0}
    items = []
    for code, m in mats.items():
        if m.get("active") is False or code.startswith("CUT-") or m.get("type") not in ("accessory", "fabric"):
            continue
        u = use[code]
        lvl, why = _flag_material(m, u)
        items.append((0 if lvl == "MERAH" else 1 if lvl == "KUNING" else 2, m.get("type") != "fabric", code, m, u, lvl, why))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    for _o, _t, code, m, u, lvl, why in items:
        unit = m.get("unit") or ""
        pack = float(m.get("pack_size") or 0)
        ws.append([code, m.get("name"), m.get("type"), m.get("category_name") or m.get("category"), unit,
                   m.get("purchase_uom") or m.get("pack_unit") or unit, pack if pack > 1 else 1, None, float(m.get("unit_cost") or 0),
                   float(m.get("min_stock") or 0) or None, "",
                   _per_piece(m), len(u["models"]), u["boms"], round(u["qty_sum"] / u["boms"], 4) if u["boms"] else None,
                   u["max_cost"] or None, u["max_model"] or "", u["max_share"] or None, lvl, why])
        i = ws.max_row
        fill = RED if lvl == "MERAH" else YELLOW if lvl == "KUNING" else None
        if fill:
            for c in ws[i]:
                c.fill = fill
        ws.cell(row=i, column=REVIEW_COLS.index("harga_per_satuan_beli") + 1).fill = YELLOW
        for col in ("harga_per_satuan_dasar_sekarang", "harga_per_pcs_atau_m_sekarang"):
            ws.cell(row=i, column=REVIEW_COLS.index(col) + 1).fill = BLUE
        ws.cell(row=i, column=len(REVIEW_COLS)).alignment = WRAP
        stats["material"] += 1
        if lvl:
            stats["merah" if lvl == "MERAH" else "kuning"] += 1
        stats["aksesoris" if m.get("type") == "accessory" else "kain"] += 1
    _widths(ws, (14, 42, 10, 16, 12, 12, 18, 22, 24, 10, 14, 22, 12, 12, 16, 18, 16, 14, 10, 80))
    ws.freeze_panes = "C2"

    # ── HPP_MODEL ──
    ws = wb.create_sheet("HPP_MODEL")
    _head(ws, HPP_COLS)
    seen = set()
    for r in sorted(bom_rows, key=lambda r: -r[3]):
        if r[0] in seen:  # satu baris per model (BOM termahal)
            continue
        seen.add(r[0])
        ws.append(r)
        if r[10]:
            for c in ws[ws.max_row]:
                c.fill = RED if r[10] == "MERAH" else YELLOW
    _widths(ws, (12, 20, 16, 14, 14, 16, 16, 12, 48, 18, 10, 60))
    ws.freeze_panes = "C2"
    stats["model_hpp_merah"] = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r[10] == "MERAH")

    # ── BOM_BARIS_MAHAL ──
    ws = wb.create_sheet("BOM_BARIS_MAHAL")
    _head(ws, LINE_COLS)
    for r in sorted(line_rows, key=lambda r: -r[10])[:200]:
        ws.append(r)
        if r[12]:
            for c in ws[ws.max_row]:
                c.fill = RED if r[12] == "MERAH" else YELLOW
    _widths(ws, (12, 20, 16, 16, 42, 10, 8, 16, 12, 20, 16, 12, 10))
    ws.freeze_panes = "D2"

    # ── KAIN_PER_MODEL ──
    ws = wb.create_sheet("KAIN_PER_MODEL")
    _head(ws, ["kode_model", "nama_model", "varian_bom", "kode_kain", "nama_kain", "qty_kain_per_pcs", "satuan", "harga_per_satuan", "biaya_kain_per_pcs", "porsi_hpp_%"])
    for r in sorted(cut_rows, key=lambda r: -r[8]):
        ws.append(r)
        unit = norm_unit(r[6])
        if r[5] > CUT_QTY_MAX.get(unit, 1e9) or (r[7] and unit == "kg" and not FAB_KG[0] <= r[7] <= FAB_KG[1]) or (r[7] and unit == "yard" and not FAB_YARD[0] <= r[7] <= FAB_YARD[1]):
            for c in ws[ws.max_row]:
                c.fill = RED
    _widths(ws, (12, 20, 16, 16, 36, 16, 8, 16, 18, 12))
    ws.freeze_panes = "D2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), stats
