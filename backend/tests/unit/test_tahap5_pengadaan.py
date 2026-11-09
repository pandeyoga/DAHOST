"""Tahap 5 · audit form Pengadaan / Gudang / Aksesoris (7 Nov 2026) — penjaga regresi sisi layar.

Perbaikannya ada di frontend (tanpa perubahan backend), jadi uji ini membaca SUMBER layar dan memastikan
pola yang salah tidak kembali:
  · isian yang wajib dari master tidak lagi teks bebas (UUID material di Penyesuaian, supplier di PR aksesoris,
    master aksesoris, penerimaan tanpa PO, roll kain manual);
  · Penerimaan Barang bisa memilih PO "Diterima Sebagian" dan mengisi SISA qty;
  · pemilih bersama (lokasi penyimpanan, satuan, master warna/ukuran/model/barang jadi) bukan <select> polos;
  · lokasi asal Karantina manual tidak dipilihkan otomatis; Opname tidak menawarkan ruang kantor;
  · tipe Penyesuaian menentukan tanda qty.
Satu perbaikan backend: daftar item aksesoris kini membawa `supplier` & `notes` (dulu tidak ⇒ form Ubah
menimpanya jadi kosong setiap kali disimpan).
Uji sumber layar dilewati bila folder frontend tidak ikut (mis. image backend saja).
"""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
ERP = ROOT.parent / "frontend" / "src" / "components" / "erp"


def src(rel: str) -> str:
    p = ERP / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


NO_NATIVE_SELECT = [
    "PurchaseOrderModule.jsx", "ProcurementRequestModule.jsx", "InventoryScrapModule.jsx",
    "RahazaMaterialsModule.jsx", "WHReturnsModule.jsx", "WeeklyShoppingListModule.jsx",
    "MaterialCostHistoryModule.jsx", "WMSBarcodeModule.jsx", "AccessoriesReports.jsx", "WMSModule.jsx",
    "StockThresholdsModule.jsx", "RahazaFGInventoryModule.jsx", "StorageLocationSelect.jsx",
    "uom/UomPicker.jsx", "masters/MasterSelects.jsx", "UomEditor.jsx",
]


@pytest.mark.parametrize("rel", NO_NATIVE_SELECT)
def test_tanpa_select_polos(rel):
    assert not re.search(r"<select\b", src(rel)), f"{rel} masih memakai <select> polos — pakai SmartNativeSelect"


def test_penyesuaian_material_dari_master_dan_tanda_qty():
    s = src("InventoryScrapModule.jsx")
    assert 'placeholder="UUID material"' not in s
    assert re.search(r'<SmartNativeSelect[^>]*\n?[^<]*data-testid="adj-material-id"', s) or \
        ('data-testid="adj-material-id"' in s and "materialOptionLabel(m)" in s)
    assert "sign: -1" in s and "isi qty negatif" in s


def test_penerimaan_po_sebagian_dan_sisa_qty():
    s = src("ReceivingModule.jsx")
    assert "status=partially_received" in s
    assert "qty_remaining" in s and "remainingOf(item)" in s
    assert 'data-testid="gr-supplier-select"' in s and "/api/procurement/suppliers/options" in s
    assert "alert(" not in s


def test_supplier_aksesoris_dari_master():
    s = src("AccessoryModule.jsx")
    assert "useSupplierOptions" in s
    assert 'data-testid="acc-supplier-select"' in s and 'data-testid="pr-supplier"' in s
    assert 'placeholder="Nama supplier..."' not in s and "placeholder:'CV. Supplier'" not in s


def test_roll_kain_tertaut_master():
    # 10 Nov 2026 (keputusan owner): form roll MANUAL dihapus — roll lahir dari penerimaan / impor stok awal
    # (penjaga lengkap: test_roll_kain_tanpa_manual.py). Yang tersisa di layar ini: posisi dari master gudang.
    s = src("WMSFabricRollsModule.jsx")
    assert "createPick" not in s and "fd.get('material_id')" not in s
    assert 'data-testid="create-roll-btn"' not in s
    assert 'data-testid="putaway-position-select"' in src("warehouse/RollPutawayPopup.jsx")


def test_karantina_lokasi_tidak_dipilihkan_dan_opname_tanpa_kantor():
    q = src("QuarantineModule.jsx")
    assert "from_location_id: (locations[0]" not in q
    o = src("WMSOpnameScanModule.jsx")
    assert "l.type !== 'kantor'" in o


def test_po_kontak_ikut_supplier_baru():
    for rel in ("PurchaseOrderModule.jsx", "ProcurementRequestModule.jsx"):
        s = src(rel)
        assert "s?.phone || prev.vendor_contact" not in s and "s?.phone || p.vendor_contact" not in s, rel


def test_konfirmasi_aplikasi_bukan_window_confirm():
    for rel in ("PurchaseOrderModule.jsx", "procurement/SupplierMasterModule.jsx"):
        assert "window.confirm(" not in src(rel), rel


def test_pr_validasi_semua_baris():
    s = src("ProcurementRequestModule.jsx")
    assert "if (!items[0].name.trim())" not in s
    assert "harus lebih dari 0" in s and "items: filled.map" in s


def test_label_material_bersatuan():
    lib = (ROOT.parent / "frontend" / "src" / "lib" / "materialFields.js")
    if not lib.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    assert "export function materialOptionLabel" in lib.read_text(encoding="utf-8")
    for rel in ("PurchaseOrderModule.jsx", "ProcurementRequestModule.jsx", "procurement/SupplierMasterModule.jsx"):
        assert "materialOptionLabel(m)" in src(rel), rel


def test_item_aksesoris_membawa_supplier_dan_catatan():
    """Respons daftar/detail item aksesoris harus memuat supplier & catatan supaya form Ubah tidak
    mengirim balik nilai kosong (PUT menulis setiap kunci yang dikirim)."""
    import routes.dewi_accessories_items as items_mod
    mat = {"id": "m1", "code": "ACC-0001", "name": "Kancing", "type": "accessory", "unit": "pcs",
           "supplier": "PT Uji Sintetis", "notes": "catatan uji"}
    out = items_mod._material_to_acc_item(mat, 3.0, {})
    assert out["supplier"] == "PT Uji Sintetis"
    assert out["notes"] == "catatan uji"
    # dokumen lama tanpa kunci → string kosong (bukan None) supaya form tetap terkontrol
    out2 = items_mod._material_to_acc_item({"id": "m2", "name": "X", "type": "accessory"}, 0.0, {})
    assert out2["supplier"] == "" and out2["notes"] == ""
