"""Katalog Marketing ← master produk (4 Nov 2026).

640 item impor Excel (sheet 14_KATALOG_JUAL) tidak punya `catalog_id`, sehingga Manajemen Katalog —
yang membaca per katalog — hanya menampilkan item contoh. Pilihan toko di layar katalog juga selalu
kosong (respons daftar toko dibaca sebagai `d.accounts`).
"""
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(*parts):
    p = os.path.join(ROOT, *parts)
    if not os.path.exists(p):
        pytest.skip(f"{p} tidak ada di lingkungan ini")
    return open(p, encoding="utf-8").read()


def test_impor_excel_mengisi_catalog_id():
    src = _read("..", "scripts", "import_master_template.py")
    block = src[src.index('if want("14_KATALOG_JUAL")'):src.index('if want("15_KOL_KREATOR")')]
    assert "ensure_catalog" in block
    assert '"catalog_id": catalog_of[acc[ak]]' in block


def test_migrasi_tautkan_item_impor_ada_dan_aman():
    src = _read("scripts", "migrations", "2026_11_04_katalog_dari_master.py")
    assert "--apply" in src and "delete" not in src.lower().replace("tanpa hapus", "")
    assert "len(cats) > 1" in src          # toko dengan >1 katalog tidak ditebak
    assert "existing_fg" in src            # tidak membuat item dobel


def test_layar_katalog_membaca_daftar_toko_dengan_benar():
    src = _read("..", "frontend", "src", "components", "erp", "CatalogManagementModule.jsx")
    assert "Array.isArray(d) ? d : (d.accounts || [])" in src
    assert "{a.platform} — {a.name}</option>" not in src
    assert "seed-demo" not in src


def test_migrasi_menonaktifkan_item_contoh_tanpa_master():
    src = _read("scripts", "migrations", "2026_11_04_katalog_dari_master.py")
    assert "'source': 'seed_demo'" in src and "'is_active': False" in src
    assert "'fg_material_id': {'$in': [None, '']}" in src   # item contoh yang sudah ditautkan tidak disentuh


def test_katalog_kreator_satu_sumber():
    ops = _read("routes", "marketing_kol_ops.py")
    portal = _read("routes", "marketing_kol_portal.py")
    assert "marketing_creator_catalog" not in ops.replace("`marketing_creator_catalog`", "")
    assert "db.marketing_creator_catalog" not in portal
    assert "raise HTTPException(410, KOL_CATALOG_ONE_DOOR)" in ops
    assert "item['is_published']" in portal
    kol = _read("..", "frontend", "src", "components", "erp", "KOLCreatorModule.jsx")
    assert "kol/catalog" not in kol and "kol-catalog-one-door" in kol
