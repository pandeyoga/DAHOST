"""Pemindai UI (scripts/ui_audit/scan_ui.py) — aturan revisi 2 panduan (4 Nov 2026).

Menjaga alat audit tetap menangkap: layar tanpa cetakan PageLayout, daftar/tabel di popup, jarak besar,
dan entri registri `lazyRetry(() => import(...))` (dulu portal cutting/collaboration terbaca 0 berkas).
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCAN = ROOT / "scripts" / "ui_audit" / "scan_ui.py"
if not SCAN.exists():
    pytest.skip("scripts/ui_audit tidak ada di lingkungan ini", allow_module_level=True)

spec = importlib.util.spec_from_file_location("scan_ui", SCAN)
scan_ui = importlib.util.module_from_spec(spec)
sys.modules["scan_ui"] = scan_ui
spec.loader.exec_module(scan_ui)


def _hits(tmp_path, name, src, screen=True):
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    scan_ui.ROOT = tmp_path   # relative_to() di scan_special
    return [h["rule"] for h in scan_ui.scan_special({f}, {f} if screen else set())]


def test_layar_tanpa_cetakan_ditandai(tmp_path):
    assert "CETAKAN-TIDAK-DIPAKAI" in _hits(tmp_path, "A.jsx", "export default function A(){return <div/>}")
    assert "CETAKAN-TIDAK-DIPAKAI" not in _hits(tmp_path, "B.jsx", "export default () => <PageLayout title='x'/>")
    assert "CETAKAN-TIDAK-DIPAKAI" not in _hits(tmp_path, "C.jsx", "const C = () => <div/>", screen=False)


def test_daftar_di_popup_ditandai(tmp_path):
    sheet = "<Sheet><SheetContent>{rows.map(r => <p>{r}</p>)}</SheetContent></Sheet>"
    dialog_form = "<Dialog><DialogContent><select>{opts.map(o => <option/>)}</select></DialogContent></Dialog>"
    dialog_table = "<Dialog><DialogContent><table><tbody/></table></DialogContent></Dialog>"
    assert "POPUP-DAFTAR" in _hits(tmp_path, "S.jsx", sheet, screen=False)
    assert "POPUP-DAFTAR" not in _hits(tmp_path, "F.jsx", dialog_form, screen=False)
    assert "POPUP-DAFTAR" in _hits(tmp_path, "T.jsx", dialog_table, screen=False)


def test_jarak_besar_ditandai(tmp_path):
    assert "JARAK-BESAR" in _hits(tmp_path, "J.jsx", '<div className="space-y-6 py-12">', screen=False)
    assert "JARAK-BESAR" not in _hits(tmp_path, "K.jsx", '<div className="space-y-4 py-2 mb-4">', screen=False)


def test_entri_registri_lazy_langsung_terbaca():
    f = scan_ui._entry_file("lazyRetry(() => import('./cutting/CuttingDashboard')),", {})
    assert f is not None and f.name.startswith("CuttingDashboard")
