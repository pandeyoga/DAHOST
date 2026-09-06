#!/usr/bin/env python3
"""scripts/prepare_golive_workbook.py — SALINAN go-live dari berkas master owner.

    python3 scripts/prepare_golive_workbook.py SUMBER.xlsx TUJUAN.xlsx

Berkas asli TIDAK diubah. Yang dilakukan pada salinan — semuanya keputusan owner
(2026-09), bukan tebakan, dan setiap perubahan dicatat di sheet DAFTAR_PERBAIKAN:
  1. 01_LOKASI: kolom `peran` diisi (fg/kain/aksesoris/karantina/cutting) sesuai pemetaan owner.
  2. 14_KATALOG_JUAL: pasangan toko–SKU yang KONFLIK harga (dua baris, harga beda) dikeluarkan
     SELURUHNYA dari sheet katalog dan dipindah ke DAFTAR_PERBAIKAN menunggu jawaban klien.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

# Keputusan owner: peran lokasi (kain = GD-L2 Gudang Lantai 2).
PERAN = {"GD-L1-RAK": "fg", "GD-L1-ACC": "aksesoris", "GD-L1-QC": "karantina",
         "GD-L2-CUT": "cutting", "GD-L2": "kain"}
CAT_KEYS = ("harga_jual", "harga_coret", "tautan_produk", "aktif")


def header_map(ws) -> dict[str, int]:
    return {str(c.value).strip().lower(): i for i, c in enumerate(ws[1], start=1) if c.value}


def fill_location_roles(wb, notes: list) -> None:
    ws = wb["01_LOKASI"]
    h = header_map(ws)
    if "peran" not in h:
        ws.cell(row=1, column=ws.max_column + 1, value="peran")
        h = header_map(ws)
    seen = set()
    for row in ws.iter_rows(min_row=2):
        code = str(row[h["kode"] - 1].value or "").strip().upper()
        if code in PERAN:
            row[h["peran"] - 1].value = PERAN[code]
            seen.add(code)
            notes.append(["01_LOKASI", "Peran lokasi diisi (keputusan owner)", code, 1,
                          f"peran = {PERAN[code]}; kode ZNA-* bawaan sistem tidak dipakai lagi"])
    missing = set(PERAN) - seen
    if missing:
        raise SystemExit(f"Kode lokasi untuk peran tidak ada di sheet: {sorted(missing)}")


def extract_catalog_conflicts(wb, notes: list) -> int:
    ws = wb["14_KATALOG_JUAL"]
    h = header_map(ws)
    groups: dict[tuple, list[int]] = defaultdict(list)
    values: dict[int, tuple] = {}
    for row in ws.iter_rows(min_row=2):
        r = row[0].row
        ak = str(row[h["kode_akun"] - 1].value or "").strip().upper()
        sku = str(row[h["sku"] - 1].value or "").strip().upper()
        if not ak and not sku:
            continue
        values[r] = tuple(str(row[h[k] - 1].value or "").strip() if k in h else "" for k in CAT_KEYS)
        groups[(ak, sku)].append(r)
    drop: list[int] = []
    for (ak, sku), rows in groups.items():
        if len(rows) > 1 and len({values[r] for r in rows}) > 1:
            harga = sorted({values[r][0] for r in rows})
            for r in rows:
                drop.append(r)
                notes.append(["14_KATALOG_JUAL", "KONFLIK harga toko–SKU — DIKELUARKAN, menunggu jawaban klien",
                              f"{ak} / {sku} (baris asli {r})", 1,
                              f"Harga mana yang benar: {' vs '.join(harga)}? Tautan berbeda → kemungkinan listing "
                              "satuan vs bundel; bila keduanya sah, bundel perlu SKU sendiri."])
    for r in sorted(drop, reverse=True):
        ws.delete_rows(r, 1)
    return len(drop)


def main(src: Path, dest: Path) -> None:
    if dest.exists():
        raise SystemExit(f"Tujuan sudah ada: {dest}")
    wb = load_workbook(src)
    notes: list = []
    fill_location_roles(wb, notes)
    dropped = extract_catalog_conflicts(wb, notes)
    if "DAFTAR_PERBAIKAN" not in wb.sheetnames:
        ws = wb.create_sheet("DAFTAR_PERBAIKAN")
        ws.append(["Sheet", "Perkara", "Kode / baris", "Jumlah baris", "Pertanyaan"])
    ws = wb["DAFTAR_PERBAIKAN"]
    for n in notes:
        ws.append(n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    print(f"Salinan go-live: {dest}\n  peran lokasi diisi : {len(PERAN)}\n  baris katalog konflik dikeluarkan: {dropped}"
          f"\n  catatan DAFTAR_PERBAIKAN ditambah : {len(notes)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
