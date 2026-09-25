"""gap_fokus — DATA_YANG_PERLU_DIISI_DA_FOKUS.xlsx: berkas isian yang HANYA memuat yang masih perlu diisi klien
(BOM_AKSESORIS · VARIAN_BARU · MATERIAL). Semua kolom lain sudah terisi dari sistem; klien hanya mengisi sel KUNING.
Sel BIRU = sudah diisi otomatis oleh sistem (mis. varian dari nama bahan pembeda) — cukup diperiksa.
Berkas ini bisa diunggah balik apa adanya ke layar yang sama (kolom-kolom importir tidak diubah posisinya).
"""
from __future__ import annotations

import difflib
import io
import re

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from core import gap_sisa
from core.bom_fill import CATEGORIES, _SPLIT_RE, _is_kept_line, _variants_label, clean, load_model_variants, match_tokens, target_variants
from core.master_fill import BOM_COLS, MAT_COLS, _head

YELLOW = PatternFill("solid", fgColor="FFF2CC")   # wajib diisi
BLUE = PatternFill("solid", fgColor="DDEBF7")     # diisi otomatis — periksa
GREY = PatternFill("solid", fgColor="EDEDED")     # tidak perlu diubah
BOLD = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")

BOM_FOKUS_COLS = BOM_COLS + ["yang_perlu_diisi"]
VARIAN_FOKUS_COLS = gap_sisa.VARIAN_BARU_COLS
MAT_FOKUS_COLS = MAT_COLS
RINGKASAN_COLS = ["kode_model", "nama_model", "kategori", "varian_aktif", "varian_tanpa_bom", "varian_tanpa_aksesoris", "aksesoris_di_bom", "status", "isi_di_sheet", "di_berkas_anda"]
_SIZE_RE = re.compile(r"\b(?:size|uk|ukuran)\s*[:.]?\s*(xxl|xl|l|m|s|allsize|all size|std|jmb)\b", re.I)

PETUNJUK = [
    ("DATA YANG MASIH PERLU DIISI — FOKUS (BOM · VARIAN BARU · MATERIAL)", True),
    ("Berkas ini hanya berisi yang masih kurang. Semua baris sudah terisi dari sistem — Anda cukup mengisi sel KUNING.", False),
    ("", False),
    ("WARNA SEL", True),
    ("  KUNING  = wajib Anda isi.", False),
    ("  BIRU    = sudah diisi otomatis oleh sistem (mis. varian ditebak dari nama bahan 'Kancing … warna Mahogany'). Periksa; ubah bila salah.", False),
    ("  ABU-ABU = tidak perlu diubah (sudah benar / diselesaikan di sheet lain).", False),
    ("", False),
    ("URUTAN KERJA (3 langkah)", True),
    ("  0. Sheet RINGKASAN_MODEL — daftar SEMUA model yang BOM-nya belum lengkap (sama persis dengan papan Kelengkapan Data R&D), status per model,", False),
    ("     dan di sheet mana ia diisi. Baris ABU-ABU = semua SKU model itu sudah nonaktif (tidak dijual) → tidak perlu BOM, tidak muncul di sheet lain.", False),
    ("  1. Sheet VARIAN_BARU — model yang belum punya SKU: isi 'ukuran' (pilih dari ukuran_tersedia). kode_warna sudah disarankan (biru).", False),
    ("     SKU MODEL-WARNA-UKURAN + barang jadinya dibuat otomatis saat diunggah; harga_jual boleh dikosongkan.", False),
    ("  2. Sheet BOM_AKSESORIS — kelompok bahan yang MASIH butuh isian Anda (ada sel kuning). Kolom paling kanan 'yang_perlu_diisi' menyebut persis apa yang kurang di baris itu.", False),
    ("     Baris ber-kode_model = awal kelompok; baris di bawahnya (kode_model kosong) = bahan lain kelompok yang sama. Jangan hapus baris yang sudah benar.", False),
    ("     Kolom 'varian' = warna/ukuran pemakai bahan itu, dipisah koma, pilih dari 'varian_tersedia'. Kosong = semua varian model.", False),
    ("     Model yang belum punya SKU juga sudah punya kelompok kosong di sini — isi bahannya; SKU-nya dibuat dari VARIAN_BARU pada unggahan yang sama.", False),
    ("     Varian yang belum punya BOM, atau BOM-nya belum punya aksesoris: aksesorisnya sudah disalin (biru) dari BOM varian lain model yang sama — periksa, ubah bila berbeda.", False),
    ("     Kelengkapan dinilai PER VARIAN: model dianggap lengkap hanya bila SEMUA variannya punya BOM ber-aksesoris (kolom varian_tanpa_aksesoris di RINGKASAN).", False),
    ("     Sheet BOM_OTOMATIS — kelompok yang sudah diisi otomatis oleh sistem (varian biru) atau selesai lewat sheet lain (VARIAN_BARU/MATERIAL).", False),
    ("     Tidak ada sel kuning di sana: cukup periksa. Sheet ini IKUT DITERAPKAN saat diunggah balik — biarkan apa adanya, jangan dihapus.", False),
    ("  3. Sheet MATERIAL — bahan yang harganya masih 0 atau isi kemasannya belum diketahui. Isi 'harga_per_satuan_beli' (harga 1 roll / 1 m / 1 pack)", False),
    ("     dan, bila diminta, 'isi_per_satuan_beli' = berapa pcs dalam 1 roll/pack. satuan_beli sudah diisi sama dengan satuan dasar.", False),
    ("", False),
    ("UNGGAH BALIK berkas ini di Portal Keuangan → Master Akuntansi → Impor Harga · Rekening · BOM → 'Terapkan semua sheet'.", True),
    ("  Baris yang sel kuningnya dibiarkan kosong TIDAK diubah — aman diunggah sebagian, lalu unduh lagi berkas FOKUS untuk sisanya.", False),
    ("  Kode bahan lihat sheet REF_AKSESORIS (hanya referensi, tidak perlu diisi).", False),
]


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", clean(s).lower())


def _widths(ws, widths):
    for i, w in enumerate(widths):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w


def _fill(ws, row_idx: int, cols: list[str], names: list[str], fill: PatternFill) -> None:
    for n in names:
        ws.cell(row=row_idx, column=cols.index(n) + 1).fill = fill


def _blank_group(ws, code: str, name: str, varian: str, vlabel: str, todo: str, n: int = 3) -> None:
    """Kelompok BOM kosong (baris pertama ber-kode_model, sisanya bahan lain kelompok yang sama) — sel kuning wajib diisi."""
    for k in range(n):
        ws.append([code if k == 0 else "", name if k == 0 else "", "", "", None, "", "", varian if k == 0 else "",
                   vlabel if k == 0 else "", todo if k == 0 else ""])
        _fill(ws, ws.max_row, BOM_FOKUS_COLS, ["kode_material", "qty_per_pcs"], YELLOW)


def _sibling_bom(boms: list[dict], v: dict) -> dict | None:
    """BOM varian saudara: ukuran sama diutamakan, lalu warna sama, lalu apa saja yang punya aksesoris."""
    with_acc = [b for b in boms if any(not _is_kept_line(ln) for ln in b.get("materials") or [])]
    for pick in (lambda b: b.get("size_id") == v.get("size_id"),
                 lambda b: (b.get("color_code") or "").upper() == (v.get("color_code") or "").upper(),
                 lambda b: True):
        hit = next((b for b in with_acc if pick(b)), None)
        if hit:
            return hit
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SARAN VARIAN — dari nama bahan PEMBEDA antar-kelompok satu model (bukan tebakan importir)
# ═══════════════════════════════════════════════════════════════════════════
def suggest_varian(distinct_names: list[str], variants: list[dict]) -> tuple[str, str]:
    """(saran, dasar). Saran hanya bila TEPAT satu warna (dan ≤1 ukuran) ditemukan pada nama bahan pembeda."""
    text = " ".join(distinct_names)
    ntext = _norm(text)
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    colors: dict[str, str] = {}
    for v in variants:
        name = clean(v.get("color_name") or "")
        code = (v.get("color_code") or "").upper()
        if len(_norm(name)) >= 3 and _norm(name) in ntext:
            colors[name] = name
        elif len(code) >= 3 and code.lower() in words:
            colors[name or code] = code
        elif len(_norm(name)) >= 4 and " " not in name.strip() and difflib.get_close_matches(_norm(name), [w for w in words if len(w) >= 4], n=1, cutoff=0.85):
            colors[name] = difflib.get_close_matches(_norm(name), [w for w in words if len(w) >= 4], n=1, cutoff=0.85)[0]  # typo: Maron → MAROON
    sizes_avail = {(v.get("size_code") or "").upper() for v in variants}
    sizes = {m.group(1).upper().replace(" ", "") for m in _SIZE_RE.finditer(text)} & sizes_avail
    if len(colors) != 1 or len(sizes) > 1:
        return "", ""
    color = next(iter(colors))
    parts = [color] + sorted(sizes)
    hit = next((n for n in distinct_names if _norm(colors[color]) in _norm(n)), distinct_names[0] if distinct_names else "")
    return ", ".join(parts), hit


def _groups_in_file(rows: list[tuple]) -> dict[int, dict]:
    """head_row → {model_code, codes:set, names:{code:name}} dari baris BOM_AKSESORIS berkas."""
    heads = gap_sisa.group_header_rows(rows)
    out: dict[int, dict] = {}
    for r_idx, h in heads.items():
        src = rows[r_idx - 2]
        g = out.setdefault(h, {"model_code": clean(rows[h - 2][0]).upper(), "codes": set(), "names": {}})
        code = clean(src[2]).upper()
        if code:
            g["codes"].add(code)
            g["names"][code] = clean(src[3])
    return out


async def _variants_by_code(db, model_codes: set[str]) -> dict[str, list[dict]]:
    models = await db.rahaza_models.find({"code": {"$in": list(model_codes)}}, {"_id": 0, "id": 1, "code": 1}).to_list(5000)
    vmap = await load_model_variants(db, [m["id"] for m in models])
    return {m["code"]: vmap.get(m["id"]) or [] for m in models}


async def bom_fokus_rows(db, parsed: dict, rows: list[tuple]) -> tuple[list[list], list[dict], dict]:
    """→ (baris sheet, gaya per baris [{row_i, fills:[(kolom, fill)]}], stats)."""
    heads = gap_sisa.group_header_rows(rows)
    groups = _groups_in_file(rows)
    by_head: dict[int, list[dict]] = {}
    for i in parsed.get("bom_issues") or []:
        if i["kategori"] == "model_dihentikan":
            continue
        by_head.setdefault(heads.get(i["row"], i["row"]), []).append(i)
    vars_by_code = await _variants_by_code(db, {g["model_code"] for g in groups.values()})
    # bahan yang ada di SEMUA kelompok satu model = bukan pembeda
    per_model: dict[str, list[set]] = {}
    for g in groups.values():
        per_model.setdefault(g["model_code"], []).append(g["codes"])
    common = {mc: set.intersection(*sets) if len(sets) > 1 else set() for mc, sets in per_model.items()}

    out: list[list] = []
    styles: list[dict] = []
    stats = {"kelompok": 0, "varian_disarankan": 0, "varian_manual": 0, "baris": 0}
    for h in sorted(by_head):
        members = [r for r in sorted(heads) if heads[r] == h] or [h]
        g = groups.get(h) or {"model_code": "", "codes": set(), "names": {}}
        variants = vars_by_code.get(g["model_code"]) or []
        vlabel = _variants_label(variants) if variants else ""
        group_issues = [i for i in by_head[h] if i["row"] == h and i["kategori"] in ("kelompok_tanpa_varian", "warna_tak_dikenal", "model_tanpa_sku", "model_tak_dikenal")]
        stats["kelompok"] += 1
        saran, dasar = "", ""
        if any(i["kategori"] == "kelompok_tanpa_varian" for i in group_issues) and variants:
            distinct = [g["names"][c] for c in sorted(g["codes"] - common.get(g["model_code"], set()))]
            saran, dasar = suggest_varian(distinct, variants)
            if saran:
                colors, sizes, _un = match_tokens([t for t in _SPLIT_RE.split(saran) if t.strip()], variants)
                if not target_variants({"targets": {"colors": sorted(colors), "sizes": sorted(sizes)}}, variants):
                    saran = ""
        for r in members:
            src = rows[r - 2] if 0 <= r - 2 < len(rows) else (None,) * 9
            row_issues = [i for i in by_head[h] if i["row"] == r and i not in group_issues]
            varian_val = src[7]
            fills: list[tuple[str, PatternFill]] = []
            todo: list[str] = []
            if r == h:
                for i in group_issues:
                    k = i["kategori"]
                    if k == "kelompok_tanpa_varian":
                        if saran:
                            varian_val = saran
                            fills.append(("varian", BLUE))
                            todo.append(f"varian diisi otomatis dari bahan pembeda '{dasar}' → periksa; ubah bila salah")
                            stats["varian_disarankan"] += 1
                        else:
                            fills.append(("varian", YELLOW))
                            todo.append("isi kolom varian: pilih warna/ukuran dari varian_tersedia (pisah koma)")
                            stats["varian_manual"] += 1
                    elif k == "warna_tak_dikenal":
                        fills.append(("varian", YELLOW))
                        todo.append(f"ganti '{i.get('token')}' di kolom varian dengan salah satu dari varian_tersedia")
                    elif k == "model_tanpa_sku":
                        fills.append(("varian", GREY))
                        todo.append(f"tidak ada yang diisi di sini — isi 'ukuran' model {g['model_code']} di sheet VARIAN_BARU; kelompok ini otomatis ikut")
                    elif k == "model_tak_dikenal":
                        fills.append(("kode_model", YELLOW))
                        todo.append("kode model tidak ada di master — perbaiki kode_model")
            for i in row_issues:
                k, det = i["kategori"], i.get("detail", "")
                if k == "qty_kosong":
                    fills.append(("qty_per_pcs", YELLOW))
                    todo.append("isi qty_per_pcs (contoh: 1 pcs, 60 cm, 0,5)")
                elif k == "satuan_tak_valid" and "isi_per_satuan_beli" in det:
                    fills.append(("qty_per_pcs", GREY))
                    todo.append(f"baris ini tidak diubah — isi 'isi_per_satuan_beli' (pcs per {i.get('unit_raw') or 'kemasan'}) untuk {i.get('code')} di sheet MATERIAL")
                elif k == "satuan_tak_valid":
                    m = re.search(r"satuan dasar '([^']+)'", det)
                    fills.append(("qty_per_pcs", YELLOW))
                    todo.append(f"tulis qty dengan satuan yang cocok dengan satuan dasar '{m.group(1) if m else '?'}' (contoh: 60 cm, 0,5 m)")
                elif k == "kode_tak_dikenal":
                    fills.append(("kode_material", YELLOW))
                    mm = re.search(r"mirip: ([A-Z0-9-]+)", det)
                    todo.append("ganti kode_material dengan kode di REF_AKSESORIS" + (f" (mungkin {mm.group(1)})" if mm else ""))
                elif k == "baris_tanpa_model":
                    fills.append(("kode_model", YELLOW))
                    todo.append("tulis kode_model di baris pertama kelompok")
                else:
                    todo.append(f"{CATEGORIES.get(k, k)}: {det}")
            out.append([src[0], src[1], src[2], src[3], src[4], src[5], src[6] if r != h else (src[6] or ""), varian_val,
                        vlabel if r == h else "", "; ".join(dict.fromkeys(todo)) or ("" if r != h else "sudah benar — biarkan")])
            styles.append({"fills": fills, "group": h})
            stats["baris"] += 1
    return out, styles, stats


def split_otomatis(rows: list[list], styles: list[dict]) -> tuple[list[tuple[list, dict]], list[tuple[list, dict]]]:
    """(manual, otomatis). Kelompok tanpa satu pun sel KUNING = tidak ada yang perlu diisi klien → sheet BOM_OTOMATIS."""
    manual_groups = {st["group"] for st in styles if any(f is YELLOW for _c, f in st["fills"])}
    pairs = list(zip(rows, styles))
    return [p for p in pairs if p[1]["group"] in manual_groups], [p for p in pairs if p[1]["group"] not in manual_groups]


async def build_fokus_workbook(db, parsed: dict | None, data: bytes | None) -> tuple[bytes, dict]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PETUNJUK"
    for text, bold in PETUNJUK:
        ws.append([text])
        if bold:
            ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.column_dimensions["A"].width = 150
    stats: dict = {}

    # ── RINGKASAN_MODEL: SEMUA model yang BOM-nya belum lengkap (angka = papan kelengkapan R&D); diisi di akhir ──
    from core.bom_gap import bom_gap_models
    gap_models = await bom_gap_models(db)
    ws_ring = wb.create_sheet("RINGKASAN_MODEL")
    _head(ws_ring, RINGKASAN_COLS)
    per_model_file: dict[str, dict] = {}   # kode_model → {kelompok, otomatis, perlu_isian, dilewati}
    stats["model_bom_belum_lengkap"] = len(gap_models)

    # ── VARIAN_BARU ──
    ws = wb.create_sheet("VARIAN_BARU")
    _head(ws, VARIAN_FOKUS_COLS)
    if parsed:
        vb = await gap_sisa.varian_baru_rows(db, parsed)
    else:  # tanpa berkas: model aktif yang belum punya satu pun varian (bukan yang dihentikan)
        no_sku = []
        for m in await db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).sort("code", 1).to_list(5000):
            if await db.rahaza_model_variants.count_documents({"model_id": m["id"]}) == 0:
                no_sku.append({"kategori": "model_tanpa_sku", "row": 0, "detail": "", "model_code": m["code"], "model_name": m["name"], "varian_raw": ""})
        vb = await gap_sisa.varian_baru_rows(db, {"bom_issues": no_sku})
    for r in vb:
        ws.append(r)
        i = ws.max_row
        _fill(ws, i, VARIAN_FOKUS_COLS, ["kode_warna"], BLUE if r[3] else YELLOW)
        _fill(ws, i, VARIAN_FOKUS_COLS, ["ukuran"], YELLOW)
        ws.cell(row=i, column=VARIAN_FOKUS_COLS.index("keterangan") + 1).value = \
            ("isi 'ukuran' (pilih dari ukuran_tersedia); kode_warna sudah disarankan — periksa" if r[3]
             else "isi 'kode_warna' (pilih dari kode_warna_tersedia) dan 'ukuran'")
    _widths(ws, (12, 22, 16, 12, 12, 14, 62, 90, 40))
    ws.freeze_panes = "C2"
    stats["varian_baru"] = len(vb)

    # ── BOM_AKSESORIS (butuh isian) & BOM_OTOMATIS (sudah terisi otomatis — cukup periksa) ──
    ws = wb.create_sheet("BOM_AKSESORIS")
    _head(ws, BOM_FOKUS_COLS)
    ws_oto = wb.create_sheet("BOM_OTOMATIS")
    _head(ws_oto, BOM_FOKUS_COLS)
    in_file: set[str] = set()
    if parsed:
        rows = gap_sisa.bom_rows_from_file(data or b"")
        b_rows, b_styles, b_stats = await bom_fokus_rows(db, parsed, rows)
        manual, otomatis = split_otomatis(b_rows, b_styles)
        for target, pairs in ((ws, manual), (ws_oto, otomatis)):
            for r, st in pairs:
                target.append(r)
                i = target.max_row
                for col, fill in st["fills"]:
                    target.cell(row=i, column=BOM_FOKUS_COLS.index(col) + 1).fill = fill
        in_file = {clean(r[0]).upper() for r in rows if clean(r[0])} | {g["model_code"] for g in parsed.get("bom_groups") or []}
        stats.update({f"bom_{k}": v for k, v in b_stats.items()})
        stats["bom_manual_baris"] = len(manual)
        stats["bom_otomatis_baris"] = len(otomatis)
        stats["bom_otomatis_kelompok"] = len({st["group"] for _r, st in otomatis})
        for pairs, key in ((manual, "perlu_isian"), (otomatis, "otomatis")):
            for r, st in pairs:
                if clean(r[0]):
                    per_model_file.setdefault(clean(r[0]).upper(), {"perlu_isian": 0, "otomatis": 0, "diterapkan": 0})[key] += 1
        for g in parsed.get("bom_groups") or []:
            per_model_file.setdefault(g["model_code"], {"perlu_isian": 0, "otomatis": 0, "diterapkan": 0})["diterapkan"] += 1
    # ── SEMUA model yang BOM-nya belum lengkap (logika = papan kelengkapan R&D) & belum ada di berkas ──
    n_kosong = n_tanpa_sku = n_varian_tanpa_bom = n_tanpa_bom = n_varian_tanpa_acc = 0
    for gm in gap_models:
        if gm["discontinued"] or gm["code"] in in_file:
            continue
        code, name, vs = gm["code"], gm["name"], gm["variants"]
        if not vs:  # belum punya SKU: baris BOM tetap disediakan — VARIAN_BARU & BOM_AKSESORIS diterapkan dalam satu unggahan
            n_tanpa_sku += 1
            _blank_group(ws, code, name, "", "", "model belum punya SKU — isi dulu sheet VARIAN_BARU (kode_warna + ukuran), lalu isi "
                         "kode_material (lihat REF_AKSESORIS) & qty_per_pcs di sini; varian kosong = semua varian. Kedua sheet diterapkan dalam satu unggahan")
        elif not gm["has_bom"]:  # punya varian, nol BOM
            n_tanpa_bom += 1
            _blank_group(ws, code, name, "", _variants_label(vs), f"model belum punya BOM sama sekali ({len(vs)} varian) — isi kode_material & qty_per_pcs "
                         "aksesoris (varian kosong = semua varian); kain/potongan dilengkapi di R&D → BOM")
        elif not gm["has_acc"]:  # tidak satu pun BOM punya aksesoris → satu kelompok untuk semua varian (varian tanpa BOM ikut dibuat saat diterapkan)
            n_kosong += 1
            tail = f"; {len(gm['variants_without_bom'])} varian yang belum punya BOM dibuat otomatis saat diunggah" if gm["variants_without_bom"] else ""
            _blank_group(ws, code, name, "", _variants_label(vs), "belum ada aksesoris di BOM — isi kode_material (lihat REF_AKSESORIS) & qty_per_pcs; "
                         "varian kosong = semua varian; tambah baris bila perlu" + tail)
        else:  # sebagian varian tanpa BOM / BOM tanpa aksesoris → salin dari varian saudara yang punya aksesoris (biru — periksa)
            for v, mode in [(v, "bom") for v in gm["variants_without_bom"]] + [(v, "acc") for v in gm["variants_without_acc"]]:
                if mode == "bom":
                    n_varian_tanpa_bom += 1
                else:
                    n_varian_tanpa_acc += 1
                sib = _sibling_bom(gm["boms"], v)
                acc = [ln for ln in (sib or {}).get("materials") or [] if not _is_kept_line(ln)]
                vlabel = f"{v.get('color_name') or v.get('color_code') or ''} {v.get('size_code') or ''}".strip()
                what = "belum punya BOM" if mode == "bom" else "BOM-nya belum punya aksesoris"
                if not acc:
                    _blank_group(ws, code, name, vlabel, _variants_label(vs), f"varian {v.get('sku')} {what} — isi kode_material & qty_per_pcs aksesorisnya")
                    continue
                for k, ln in enumerate(acc):
                    ws.append([code if k == 0 else "", name if k == 0 else "", ln.get("code"), ln.get("name"), ln.get("qty"), ln.get("unit"), "",
                               vlabel if k == 0 else "", _variants_label(vs) if k == 0 else "",
                               (f"varian {v.get('sku')} {what} — aksesoris disalin dari BOM varian lain; periksa, ubah bila berbeda, "
                                + ("lalu unggah (BOM varian ini dibuat otomatis)" if mode == "bom" else "lalu unggah (aksesoris ditambahkan ke BOM varian ini)")) if k == 0 else ""])
                    _fill(ws, ws.max_row, BOM_FOKUS_COLS, ["kode_material", "qty_per_pcs", "varian"], BLUE)
    stats["bom_model_tanpa_aksesoris"] = n_kosong
    stats["bom_model_tanpa_sku"] = n_tanpa_sku
    stats["bom_model_tanpa_bom"] = n_tanpa_bom
    stats["bom_varian_tanpa_bom"] = n_varian_tanpa_bom
    stats["bom_varian_tanpa_aksesoris"] = n_varian_tanpa_acc
    stats["model_dihentikan"] = sum(1 for gm in gap_models if gm["discontinued"])
    for sheet in (ws, ws_oto):
        for c in sheet[1]:
            c.alignment = WRAP
        for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
            row[BOM_FOKUS_COLS.index("yang_perlu_diisi")].alignment = WRAP
        _widths(sheet, (12, 22, 16, 40, 12, 8, 30, 26, 60, 80))
        sheet.freeze_panes = "C2"

    # ── MATERIAL: harga 0 + isi kemasan yang dibutuhkan BOM ──
    need_pack = gap_sisa.materials_needing_pack(parsed) if parsed else {}
    ws = wb.create_sheet("MATERIAL")
    _head(ws, MAT_FOKUS_COLS)
    mats = await db.rahaza_materials.find({"active": {"$ne": False}, "type": {"$ne": "fg"}, "code": {"$not": {"$regex": "^CUT-"}}},
                                          {"_id": 0}).sort("code", 1).to_list(20000)
    n_mat = 0
    for m in mats:
        price = float(m.get("unit_cost") or 0)
        no_price, pack = price <= 0, m.get("code") in need_pack
        if not no_price and not pack:
            continue
        base = m.get("unit") or ""
        todo = []
        if no_price:
            todo.append(f"isi harga_per_satuan_beli = harga 1 {base}")
        if pack:
            todo.append(f"isi isi_per_satuan_beli = berapa pcs dalam 1 {base} (dipakai BOM {need_pack[m['code']].split('dipakai BOM ')[-1]})")
        ws.append([m.get("code"), m.get("name"), m.get("type"), m.get("category_name") or m.get("category"), base,
                   base, None if pack else 1, None if no_price else price, price, m.get("min_stock") or None, "; ".join(todo)])
        i = ws.max_row
        _fill(ws, i, MAT_FOKUS_COLS, ["satuan_beli"], BLUE)
        _fill(ws, i, MAT_FOKUS_COLS, ["isi_per_satuan_beli"], YELLOW if pack else BLUE)
        _fill(ws, i, MAT_FOKUS_COLS, ["harga_per_satuan_beli"], YELLOW if no_price else BLUE)
        n_mat += 1
    _widths(ws, (14, 42, 10, 16, 12, 12, 18, 22, 22, 10, 70))
    ws.freeze_panes = "C2"
    stats["material"] = n_mat

    # ── REF_AKSESORIS (referensi) ──
    ws = wb.create_sheet("REF_AKSESORIS")
    _head(ws, ["kode_material", "nama", "tipe", "satuan_dasar", "harga_per_satuan_dasar"])
    for m in mats:
        if (m.get("type") or "").lower() != "fabric":
            ws.append([m.get("code"), m.get("name"), m.get("type"), m.get("unit"), float(m.get("unit_cost") or 0)])
    _widths(ws, (16, 44, 12, 12, 18))

    # ── isi RINGKASAN_MODEL (kolom berkas hanya terisi bila berkas klien diunggah) ──
    for gm in gap_models:
        pf = per_model_file.get(gm["code"])
        if not parsed:
            berkas = "—"
        elif not pf:
            berkas = "tidak ada di berkas Anda"
        elif not gm["variants"]:
            berkas = (f"{pf['otomatis'] + pf['perlu_isian']} kelompok aksesoris ada di berkas Anda, tetapi model ini belum punya SKU → "
                      f"isi 'ukuran' di VARIAN_BARU dulu ({pf['perlu_isian']} kelompok juga masih perlu isian di BOM_AKSESORIS)")
        else:
            berkas = (f"{pf['diterapkan']} kelompok langsung diterapkan · {pf['otomatis']} varian ditebak otomatis (BOM_OTOMATIS) · "
                      f"{pf['perlu_isian']} masih perlu isian Anda (BOM_AKSESORIS)")
        ws_ring.append([gm["code"], gm["name"], gm["category"], len(gm["variants"]), len(gm["variants_without_bom"]),
                        len(gm["variants_without_acc"]) + len(gm["variants_without_bom"]),
                        "ya" if gm["has_acc"] and not gm["variants_without_acc"] else ("sebagian" if gm["has_acc"] else "tidak"),
                        gm["status"], gm["sheet"], berkas])
        if gm["discontinued"]:
            for c in ws_ring[ws_ring.max_row]:
                c.fill = GREY
        elif pf and pf["perlu_isian"] == 0 and (pf["otomatis"] or pf["diterapkan"]):
            ws_ring.cell(row=ws_ring.max_row, column=RINGKASAN_COLS.index("di_berkas_anda") + 1).fill = BLUE
    for row in ws_ring.iter_rows(min_row=2, max_row=ws_ring.max_row):
        for c in row[7:]:
            c.alignment = WRAP
    _widths(ws_ring, (12, 22, 12, 12, 16, 20, 16, 52, 52, 70))
    ws_ring.freeze_panes = "C2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), stats
