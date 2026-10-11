#!/usr/bin/env python3
"""Bangun fixture uji importir BOM v3 (+ set isi kemasan A-LBL-0004 = 600 pcs/roll seperti di VPS).

    python3 tests/fixtures/build_bom_v3_fixture.py
→ tests/fixtures/bom_v3_test.xlsx   (berkas A: semua kategori kasus)
→ tests/fixtures/bom_v3_test_b.xlsx (berkas B: hanya DA-1101, baris kancing dihapus & qty karet 70 cm → uji ganti utuh)
"""
import os
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
HDR = ["kode_model", "nama_model", "kode_material", "nama_material", "qty_per_pcs", "satuan", "keterangan", "varian"]
ZW = "\u200b"

ROWS_A = [
    # 2  DA-1101 kelompok 1 → HTM, MHG (maroon = warna tak dikenal)
    ("DA-1101", "Lyora", "A-KRT-0003", "Karet Uk 3 cm", "60 cm", "", "", "Hitam, mahogany, maroon"),
    # 3  pcs → pack tanpa isi kemasan → satuan_tak_valid
    ("", "", "A-R45-0001", "Rit Besi 45cm", 1, "PCS", "", ""),
    # 4  zero-width space + pcs → roll lewat pack_size 600
    ("", "", ZW + "A-LBL-0004", "Label DA", "1 pcs", "", "", ""),
    # 5  Pcs → gross (3/144)
    ("", "", "A-K22-0014", "Kancing 22L Hitam", 3, "Pcs", "", ""),
    # 6  DA-1101 kelompok 2 → CRL, GRY ('Caraml' typo) · 0,6 Meter
    ("DA-1101", "Lyora", "A-KRT-0003", "Karet Uk 3 cm", "0,6", "Meter", "", "Caraml, grey"),
    # 7  kode tak dikenal
    ("", "", "A-XXX-9999", "Tidak ada", 1, "pcs", "", ""),
    # 8  TRL(roll) → base m → satuan_tak_valid
    ("", "", "A-BIS-0001", "Bisban hitam", 1, "TRL", "", ""),
    # 9  qty kosong
    ("", "", "A-K34-0008", "Kancing Mutiara", None, "", "", ""),
    # 10 DA-1202 kelompok 1 → HTM
    ("DA-1202", "Adelin", "A-K22-0014", "Kancing 22L Hitam", 3, "pcs", "", "Hitam"),
    # 11 DA-1202 kelompok 2 TANPA varian pada model banyak kelompok → dilewati (tanpa tebakan warna)
    ("DA-1202", "Adelin", "A-K22-0005", "Kancing 22L Magenta", 3, "pcs", "", ""),
    # 12 DA-1201 satu kelompok tanpa varian → semua varian
    ("DA-1201", "Lunara", "A-KRT-0003", "Karet Uk 3 cm", "60 cm", "", "", ""),
    # 13 satuan 'F' ditolak
    ("", "", "A-KRT-0003", "Karet Uk 3 cm", 1, "F", "", ""),
    # 14 model tak dikenal, 15 baris tanpa model
    ("DA-9999", "Tidak ada", "A-KRT-0003", "Karet", 1, "pcs", "", ""),
    ("", "", "A-KRT-0003", "Karet", 1, "pcs", "", ""),
    # 16 model tanpa SKU → VARIAN_BARU Hitam, Putih
    ("DA-2506", "Model tanpa SKU", "A-KRT-0003", "Karet", "60 cm", "", "", "Hitam, Putih"),
]
ROWS_B = [
    ("DA-1101", "Lyora", "A-KRT-0003", "Karet Uk 3 cm", "70 cm", "", "", "Hitam, mahogany"),
    ("", "", "A-LBL-0004", "Label DA", "1 pcs", "", "", ""),
    ("DA-1101", "Lyora", "A-KRT-0003", "Karet Uk 3 cm", "0,6", "Meter", "", "Caramel, grey"),
]


def build(path: Path, rows, with_extra: bool):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM_AKSESORIS"
    ws.append(HDR)
    for r in rows:
        ws.append(list(r))
    if with_extra:
        ws = wb.create_sheet("HARGA_JUAL_SKU")
        ws.append(["sku", "nama", "kode_model", "warna", "ukuran", "harga_saran_dari_saudara", "harga_jual", "keterangan"])
        ws.append(["DA-1202-CRM-M", "Adelin", "DA-1202", "Cream", "M", None, 155999, ""])
        ws.append(["DA-1202-DNM-M", "Adelin", "DA-1202", "Denim", "M", None, "sudah tidak dijual", ""])
        ws.append(["DA-1202-DST-M", "Adelin", "DA-1202", "Dusty", "M", 155999, None, ""])
        ws.append(["DA-0000-XXX-M", "SKU tak ada", "DA-0000", "X", "M", None, 1000, ""])  # error sheet lain → tak menghalangi scope=bom
    wb.save(path)
    print("→", path)


async def set_pack_size():
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv(ROOT / "backend" / ".env")
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    r = await db.rahaza_materials.update_one({"code": "A-LBL-0004"}, {"$set": {"pack_size": 600, "pack_unit": "roll"}})
    print("A-LBL-0004 pack_size=600:", r.modified_count)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent
    build(out / "bom_v3_test.xlsx", ROWS_A, True)
    build(out / "bom_v3_test_b.xlsx", ROWS_B, False)
    if "--no-db" not in sys.argv:
        import asyncio
        asyncio.run(set_pack_size())
