"""core.resep_kain — RESEP KAIN sebuah potongan: produk yang dipotong dari LEBIH DARI SATU kain.

KEPUTUSAN OWNER 18 Nov 2026
---------------------------
Owner: "ada bom atau product yang lebih dari 1 kain … maka yang harus ditambahkan juga adalah mekanisme cuttingnya …
bomnya harus ada dua kain atau lebih otomatis menyesuaikan roll kainnya". Contoh SPEK PRODUK: Ona (badan Rib Salur,
kerah & paspol Knit 24), Rasha (badan Hornet, lengan Shakila), Noela (rayon motif + rayon polos).

Pilihan owner:
  * POTONGAN TETAP SATU per baju (`CUT-<MODEL>-<WARNA>-<UKURAN>` = satu SET potongan semua bagian). Kirim CMT, setor,
    tagihan, dan HPP hilir tidak berubah.
  * Baris potongan di BOM membawa `fabric_recipe` = daftar kain per warna + perannya (Utama, Kombinasi, Kerah, …) +
    PERKIRAAN kebutuhan per pcs (boleh kosong). Angka ini hanya untuk rencana (isi otomatis Order Cutting, usulan
    gulungan, "Menunggu kain"); HPP tetap dari kain yang BENAR-BENAR dipotong (keputusan 12 Sep 2026 tetap berlaku).
  * Order Cutting: tiap kain resep jadi baris kain order; hasil yang memakai resep WAJIB memakai semua kainnya.
  * HPP potongan: nilai tiap kain dibagi ke hasil yang MEMAKAI kain itu menurut resep (bukan rata ke semua hasil
    order). Hasil tanpa resep tetap ikut semua kain (perilaku 10 Nov), jadi order lama angkanya tidak berubah.

Modul ini memegang aturan resep (bentuk data, validasi master, rencana kebutuhan, pembagian nilai). Fungsi tanpa
`db` MURNI supaya bisa diuji tanpa database.
"""
from __future__ import annotations

from fastapi import HTTPException

#: Saran peran di layar (teks bebas tetap diterima).
PERAN_SARAN = ("Utama", "Kombinasi", "Kerah", "Lengan", "Furing", "Kain keras")
#: Satuan kain roll yang sah sebagai bahan cutting (sama dengan `routes.cutting.INPUT_UNITS`).
SATUAN_KAIN = {"kg", "gram", "m", "cm", "yard", "inch", "roll", "rol", "gulung", "bal"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _qty(v) -> float | None:
    """Perkiraan per pcs: kosong/0/teks = belum diisi (None), bukan nol yang seolah benar."""
    if v in (None, ""):
        return None
    q = _f(v)
    return round(q, 6) if q > 0 else None


# ───────────────────────────── bentuk data (murni) ─────────────────────────────
def normalisasi(raw) -> list[dict]:
    """Rapikan isian resep dari layar/skrip. Baris tanpa kain diabaikan; kain yang sama dua kali → baris pertama."""
    out: list[dict] = []
    seen: set = set()
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        mid = str(r.get("material_id") or "").strip()
        code = str(r.get("code") or "").strip().upper()
        if not (mid or code):
            continue
        key = mid or code
        if key in seen or (code and code in seen):
            continue
        seen.update({k for k in (mid, code) if k})
        role = " ".join(str(r.get("role") or "").split())[:40]
        out.append({
            "material_id": mid or None,
            "code": code,
            "name": str(r.get("name") or "").strip(),
            "role": role or ("Utama" if not out else "Kombinasi"),
            "qty_per_pcs": _qty(r.get("qty_per_pcs")),
            "unit": str(r.get("unit") or "").strip().lower(),
        })
    return out


def resep_of_line(line: dict | None) -> list[dict]:
    """Resep sebuah baris potongan BOM / baris hasil order (kosong = produk satu kain / belum diisi)."""
    return normalisasi((line or {}).get("fabric_recipe"))


def label_kain(r: dict) -> str:
    return f"{r.get('code') or r.get('name') or 'kain'} ({r.get('role') or 'Utama'})"


# ───────────────────────────── validasi master (db) ─────────────────────────────
async def lengkapi(db, materials: list[dict]) -> list[dict]:
    """Baris potongan BOM yang membawa resep: tiap kain WAJIB kain roll aktif di master (bukan potongan, bukan
    aksesoris) — kode/nama/satuan diselaraskan ke master. Kain asal potongan (`source_material_code`) yang masih
    kosong / "KN-TBD" diisi kain pertama resep. Raise 400 dengan nama baris yang salah."""
    for line in materials or []:
        recipe = normalisasi(line.get("fabric_recipe"))
        if not recipe:
            line.pop("fabric_recipe", None)
            continue
        if not (line.get("is_cut_panel") or str(line.get("code") or "").upper().startswith("CUT-")):
            raise HTTPException(400, (
                f"Resep kain hanya untuk baris potongan (CUT-…), bukan untuk '{line.get('name') or line.get('code')}'."))
        ids = [r["material_id"] for r in recipe if r.get("material_id")]
        codes = [r["code"] for r in recipe if r.get("code")]
        found = {}
        async for m in db.rahaza_materials.find(
                {"$or": [{"id": {"$in": ids}}, {"code": {"$in": codes}}]},
                {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "type": 1, "is_cut_panel": 1, "active": 1}):
            found[m["id"]] = m
            found[(m.get("code") or "").upper()] = m
        done: list[dict] = []
        for r in recipe:
            m = found.get(r.get("material_id") or "") or found.get(r.get("code") or "")
            nama = r.get("code") or r.get("name") or "kain"
            if not m:
                raise HTTPException(400, f"Resep kain {line.get('code')}: kain {nama} tidak ada di master bahan.")
            if m.get("active") is False:
                raise HTTPException(400, f"Resep kain {line.get('code')}: kain {m.get('code')} sudah non-aktif.")
            if m.get("is_cut_panel") or str(m.get("code") or "").upper().startswith("CUT-"):
                raise HTTPException(400, (
                    f"Resep kain {line.get('code')}: {m.get('code')} adalah potongan, bukan kain roll."))
            unit = (m.get("unit") or "").lower()
            if (m.get("type") or "").lower() != "fabric" or unit not in SATUAN_KAIN:
                raise HTTPException(400, (
                    f"Resep kain {line.get('code')}: {m.get('code')} bukan kain roll "
                    f"(jenis {m.get('type') or '-'}, satuan {unit or '-'})."))
            if any(d["material_id"] == m["id"] for d in done):
                continue
            done.append({**r, "material_id": m["id"], "code": (m.get("code") or "").upper(),
                         "name": m.get("name") or "", "unit": unit})
        line["fabric_recipe"] = done
        src = str(line.get("source_material_code") or "").upper()
        if done and (not src or src.startswith("KN-TBD")):
            line["source_material_code"] = done[0]["code"]
    return materials


async def resep_bom(db, *, model_id: str, size_id: str, color: str) -> tuple[list[dict], str]:
    """Resep potongan menurut BOM aktif model+ukuran+warna → (resep, catatan). BOM warna LAIN tidak dipakai
    (kodenya kain warna lain); catatannya dikembalikan supaya layar bisa menjelaskan."""
    from core import product_costing, cut_panel_master
    if not (model_id and size_id):
        return [], ""
    bom, match = await product_costing.find_active_bom_ex(db, model_id, size_id, color or None)
    if not bom:
        return [], ""
    if match == product_costing.BOM_MATCH_OTHER:
        return [], f"BOM warna {color} belum ada — resep kain warna lain tidak dipakai."
    for ln in bom.get("materials") or []:
        if cut_panel_master.is_panel_line(ln):
            return resep_of_line(ln), ""
    return [], ""


# ───────────────────────────── rencana & aturan cutting (murni) ─────────────────────────────
def rencana_kain(outputs: list[dict]) -> list[dict]:
    """Σ kebutuhan per kain dari resep baris hasil: [{material_id, code, name, unit, roles, planned, unknown, used_by}].
    `planned` = Σ perkiraan/pcs × target pcs; `unknown` = ada hasil yang perkiraannya belum diisi."""
    acc: dict = {}
    order: list = []
    for o in outputs or []:
        pcs = _f(o.get("planned_output_qty"))
        label = o.get("label") or o.get("output_material_code") or o.get("model_code") or ""
        for r in resep_of_line(o):
            key = r.get("material_id") or r.get("code")
            row = acc.get(key)
            if not row:
                row = acc[key] = {"material_id": r.get("material_id"), "code": r.get("code"), "name": r.get("name"),
                                  "unit": r.get("unit"), "roles": [], "planned": 0.0, "unknown": False,
                                  "used_by": []}
                order.append(key)
            if r["role"] not in row["roles"]:
                row["roles"].append(r["role"])
            if label and label not in row["used_by"]:
                row["used_by"].append(label)
            if r.get("qty_per_pcs"):
                row["planned"] = round(row["planned"] + r["qty_per_pcs"] * pcs, 4)
            else:
                row["unknown"] = True
    return [acc[k] for k in order]


def kain_resep_hilang(outputs: list[dict], input_ids: set) -> list[str]:
    """Pesan untuk kain resep yang TIDAK ada di baris kain order (dipakai saat simpan order)."""
    msgs = []
    for o in outputs or []:
        miss = [r for r in resep_of_line(o) if r.get("material_id") not in input_ids]
        if miss:
            msgs.append(f"{o.get('label') or o.get('output_material_code') or 'hasil'} memakai "
                        + ", ".join(label_kain(r) for r in miss))
    return msgs


def kain_resep_belum_dipakai(outputs_pcs: list[tuple[dict, float]], used_total: dict) -> list[str]:
    """Hasil yang dilaporkan pcs-nya tetapi salah satu kain resepnya belum pernah dipakai di order ini.
    `outputs_pcs` = [(baris hasil, pcs laporan ini)], `used_total` = {material_id: kain terpakai s.d. laporan ini}."""
    msgs = []
    for o, pcs in outputs_pcs or []:
        if pcs <= 0:
            continue
        miss = [r for r in resep_of_line(o) if _f(used_total.get(r.get("material_id"))) <= 0]
        if miss:
            msgs.append(f"{o.get('label') or o.get('output_material_code') or 'hasil'}: "
                        + ", ".join(label_kain(r) for r in miss))
    return msgs


def alokasi_nilai(fabric_values: dict, panels: list[dict], recipes: list[list[dict]] | None) -> list[float]:
    """Bagi nilai kain keluar ke baris hasil → nilai per baris (urutan = `panels`).

    `fabric_values` = {material_id kain: nilai keluar}, `panels` = [{qty}] (pcs per baris), `recipes` = resep tiap
    baris (sejajar `panels`; [] = baris tanpa resep). Aturan per kain:
      * yang berhak = baris yang resepnya memuat kain itu + baris TANPA resep (kainnya tidak diketahui);
      * kain yang tidak ada di resep mana pun dan semua baris punya resep → semua baris berhak (tidak hilang);
      * bobot = pcs × perkiraan/pcs bila SEMUA yang berhak punya perkiraan untuk kain itu, selain itu pcs.
    Tanpa resep sama sekali = Σ nilai ÷ Σ pcs untuk semua baris (persis aturan 10 Nov)."""
    n = len(panels or [])
    out = [0.0] * n
    recipes = list(recipes or [])
    recipes += [[]] * (n - len(recipes))
    by_line = [{r.get("material_id"): r for r in normalisasi(rc)} for rc in recipes]
    live = [i for i in range(n) if _f(panels[i].get("qty")) > 0]
    for fid, value in (fabric_values or {}).items():
        value = _f(value)
        if value <= 0 or not live:
            continue
        hak = [i for i in live if not by_line[i] or fid in by_line[i]]
        if not hak:
            hak = list(live)
        pakai_qty = all(fid in by_line[i] and by_line[i][fid].get("qty_per_pcs") for i in hak)
        w = [_f(panels[i].get("qty")) * (by_line[i][fid]["qty_per_pcs"] if pakai_qty else 1.0) for i in hak]
        tw = sum(w)
        if tw <= 0:
            continue
        for i, wi in zip(hak, w):
            out[i] += value * wi / tw
    return [round(v, 4) for v in out]
