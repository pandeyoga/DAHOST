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


def test_kartu_per_baris_ditandai(tmp_path):
    # 2026-11-07 (Tahap 9): daftar yang tiap barisnya kartu → harus tabel + RowDetail/DetailPanel
    vendor = "{list.map(p => (\n  <GlassCard key={p.id}><b>{p.name}</b></GlassCard>\n))}"
    custom = "{rows.map((r) => <VendorCard key={r.id} row={r} />)}"
    div = '{rows.map(r => (<div key={r.id} className="rounded-xl border bg-card p-3">{r.x}</div>))}'
    stat = "{kpi.map(k => <StatCard key={k.id} {...k} />)}"
    plain = '{rows.map(r => (<div key={r.id} className="flex gap-2">{r.x}</div>))}'
    assert "KARTU-PER-BARIS" in _hits(tmp_path, "V.jsx", vendor, screen=False)
    assert "KARTU-PER-BARIS" in _hits(tmp_path, "W.jsx", custom, screen=False)
    assert "KARTU-PER-BARIS" in _hits(tmp_path, "D.jsx", div, screen=False)
    assert "KARTU-PER-BARIS" not in _hits(tmp_path, "S.jsx", stat, screen=False)
    assert "KARTU-PER-BARIS" not in _hits(tmp_path, "P.jsx", plain, screen=False)


def test_kartu_di_dalam_kartu_ditandai(tmp_path):
    nested = "<GlassCard>\n  <h3>x</h3>\n  <GlassPanel className='p-2'>y</GlassPanel>\n</GlassCard>"
    siblings = "<GlassCard>a</GlassCard>\n<GlassCard onClick={() => go(1)}>b</GlassCard>"
    selfclose = "<GlassCard>\n  <Card />\n</GlassCard>"
    content = "<Card>\n  <CardContent>x</CardContent>\n</Card>"
    assert _hits(tmp_path, "N.jsx", nested, screen=False).count("KARTU-DALAM-KARTU") == 1
    assert "KARTU-DALAM-KARTU" not in _hits(tmp_path, "B.jsx", siblings, screen=False)
    assert "KARTU-DALAM-KARTU" in _hits(tmp_path, "C.jsx", selfclose, screen=False)
    assert "KARTU-DALAM-KARTU" not in _hits(tmp_path, "E.jsx", content, screen=False)
