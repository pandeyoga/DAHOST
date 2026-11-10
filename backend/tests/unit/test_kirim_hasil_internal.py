"""Kirim hasil di Portal Produksi = serah terima ke gudang DA (permintaan owner 10 Nov 2026).

Kata owner: "kirim hasil ini kesiapa? lalu tidak bisa pilih namanya? ini kan produksi internal". Di portal internal
pilihan "Gabungkan beberapa PO milik penerima yang sama" (khusus klien maklon; daftar penerimanya dari nama klien PO,
yang kosong untuk PO internal) disembunyikan, penerima tampil baca-saja "Gudang barang jadi DA", kolom Penerima surat
jalan internal tertulis "Gudang DA", dan PO yang produksinya sudah selesai tetap bisa dipilih.
"""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp" / "engine"
       / "BuyerShipmentModule.jsx").read_text(encoding="utf-8")


def test_portal_internal_tanpa_gabung_dan_penerima_gudang_da():
    assert "const portalInternal = businessType === 'internal'" in SRC
    assert "{!(portalInternal && !consolidate) && (" in SRC          # toggle gabung tidak tampil di internal
    assert 'data-testid="internal-receiver"' in SRC and "Gudang barang jadi DA (serah terima internal)" in SRC
    assert "const GUDANG_DA = 'Gudang DA'" in SRC and "? GUDANG_DA : '—'" in SRC


def test_po_selesai_produksi_bisa_dipilih_untuk_dikirim():
    assert "SHIPPABLE_PO_STATUSES.includes(p.status)" in SRC
    for st in ("'In Production'", "'Production Complete'", "'Ready to Close'"):
        assert st in SRC.split("const SHIPPABLE_PO_STATUSES")[1].split("];")[0]
