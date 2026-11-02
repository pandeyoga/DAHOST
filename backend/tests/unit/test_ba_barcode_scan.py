"""Uji unit HERMETIK Paket 3a — fondasi barcode, label & scan (2026-11-02).

Mengunci temuan runtime `dahost_ba` (C:/…/dahost_chk/ba/s2.py):
  * Universal Scan dulu `found=false` untuk 13/13 kode stok (SKU FG, QR label FG,
    bahan, bin, lokasi, roll) — kini lewat `core.scan_resolver`;
  * opname3 resolve-item/bin dulu peka huruf & tidak mengenali QR JSON;
  * label: generator Code128 kembar (FG/bahan, bin, roll), "N/A" tercetak untuk
    dokumen tanpa kode, SKU karangan diterima endpoint `custom`.

Jalankan:  cd /app/backend && python -m pytest tests/unit -q
"""
import asyncio
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import scan_resolver as sr  # noqa: E402
from core import label_render as lr  # noqa: E402

USER = {"id": "u1", "name": "Uji", "email": "uji@x", "role": "superadmin"}
FG_SKU = "DA-2101-MHG-ALLSIZE"
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def run(coro):
    return asyncio.run(coro)


def seed_db():
    return FakeDB(
        rahaza_materials=[
            {"id": "fg1", "code": FG_SKU, "sku": FG_SKU, "type": "fg", "name": "Aisar", "unit": "pcs",
             "active": True, "variant_id": "v1", "model_code": "DA-2101", "color_name": "MAHOGANY",
             "size_code": "ALLSIZE"},
            {"id": "fg0", "code": "DA-2104-BRG-ALLSIZE", "sku": "DA-2104-BRG-ALLSIZE", "type": "fg",
             "name": "Lama", "unit": "pcs", "active": False},
            {"id": "m1", "code": "A-BIS-0001", "type": "accessory", "name": "Bisban hitam", "unit": "m",
             "active": True},
            {"id": "m2", "code": "KN-CND-DST 2", "type": "fabric", "name": "Condru", "unit": "kg",
             "active": True},
        ],
        rahaza_model_variants=[{"id": "v1", "sku": FG_SKU, "barcode": "8991234567890", "active": True}],
        marketing_catalog_items=[{"id": "c1", "sku": "TOKO-AISAR-MHG", "fg_material_id": "fg1"}],
        wh_positions=[{"id": "p1", "barcode": "GDT-FG-R01-S01-P01", "label": "Shelf 1, Slot 1",
                       "building_code": "GDT", "zone_code": "FG", "rack_code": "R01", "qty": 0}],
        rahaza_locations=[{"id": "l1", "code": "GD-L1-RAK", "name": "Rak Gudang L1", "type": "gudang",
                           "active": True}],
        wh_fabric_rolls=[{"id": "r1", "roll_no": "RL-202611-0001", "material_id": "m2",
                          "material_code": "KN-CND-DST 2", "material_name": "Condru", "uom": "kg",
                          "remaining_kg": 20, "status": "in_stock"}],
    )


def fg_qr_payload(sku=FG_SKU):
    # bentuk persis payload QR yang digambar label_render.draw_fg_label
    return json.dumps({"type": "fg", "sku": sku, "name": "Aisar", "size": "ALLSIZE",
                       "color": "MAHOGANY", "at": "2026-11-02T00:00:00+00:00"})


# ── 1. normalisasi kode ──────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    ("  DA-2101-MHG-ALLSIZE \r\n", FG_SKU),
    ("]C0DA-2101-MHG-ALLSIZE", FG_SKU),          # prefix AIM Code128
    ("]Q1{\"a\":1}", "{\"a\":1}"),               # prefix AIM QR
    ("\ufeffDA-2101\x1d-MHG-ALLSIZE\t", FG_SKU),  # BOM + GS + TAB
    ("*RL-202611-0001*", "RL-202611-0001"),      # Code39 start/stop
    ("KN-CND-DST 2", "KN-CND-DST 2"),            # spasi di tengah dipertahankan
    ("", ""), (None, ""),
])
def test_normalize_code(raw, expect):
    assert sr.normalize_code(raw) == expect


# ── 2. resolusi: semua tipe stok dikenali ────────────────────────────────────
@pytest.mark.parametrize("code,tipe,kode,via", [
    (FG_SKU, "fg", FG_SKU, "sku"),
    (FG_SKU.lower(), "fg", FG_SKU, "sku"),
    ("]C0" + FG_SKU + "\r", "fg", FG_SKU, "sku"),
    ("8991234567890", "fg", FG_SKU, "barcode_varian"),
    ("toko-aisar-mhg", "fg", FG_SKU, "sku_katalog"),
    ("a-bis-0001", "material", "A-BIS-0001", "kode"),
    ("KN-CND-DST 2", "material", "KN-CND-DST 2", "kode"),
    ("gdt-fg-r01-s01-p01", "bin", "GDT-FG-R01-S01-P01", "barcode_posisi"),
    ("GD-L1-RAK", "bin", "GD-L1-RAK", "kode_lokasi"),
    ("rl-202611-0001", "roll", "RL-202611-0001", "nomor_roll"),
])
def test_resolve_all_stock_types(code, tipe, kode, via):
    res = run(sr.resolve(seed_db(), code))
    assert res is not None, code
    assert (res["tipe"], res["kode"], res["via"]) == (tipe, kode, via)


def test_resolve_fg_qr_label_payload():
    res = run(sr.resolve(seed_db(), fg_qr_payload()))
    assert res["tipe"] == "fg" and res["id"] == "fg1" and res["sku"] == FG_SKU
    assert res["satuan"] == "pcs" and res["via"] == "qr_sku"


def test_resolve_result_shape_and_public_strips_doc():
    res = run(sr.resolve(seed_db(), FG_SKU))
    for k in ("tipe", "id", "nama", "kode", "sku", "satuan", "aktif", "via"):
        assert k in res
    assert "_doc" in res and "_doc" not in sr.public(res)


def test_inactive_fg_still_resolved_but_flagged():
    res = run(sr.resolve(seed_db(), "DA-2104-BRG-ALLSIZE"))
    assert res["tipe"] == "fg" and res["aktif"] is False


def test_active_preferred_over_inactive_same_code():
    db = seed_db()
    db.rahaza_materials.docs.insert(0, {"id": "fgX", "code": FG_SKU, "type": "fg", "name": "Lama", "active": False})
    assert run(sr.resolve(db, FG_SKU))["id"] == "fg1"


@pytest.mark.parametrize("code", ["ZZZ-TIDAK-ADA", "AST-001(", ".*", "{bukan json", "{\"type\":\"fg\"}"])
def test_unknown_or_hostile_codes_return_none(code):
    assert run(sr.resolve(seed_db(), code)) is None


def test_expect_restricts_types():
    db = seed_db()
    assert run(sr.resolve(db, FG_SKU, expect=("material",))) is None
    assert run(sr.resolve(db, "GDT-FG-R01-S01-P01", expect=("fg", "material"))) is None
    assert run(sr.resolve_item(db, "a-bis-0001"))["tipe"] == "material"
    with pytest.raises(ValueError):
        sr.parse_expect("fg,gudang")
    assert sr.parse_expect("fg, bin") == ("fg", "bin") and sr.parse_expect("") is None


def test_position_by_barcode_excludes_locations():
    db = seed_db()
    assert run(sr.position_by_barcode(db, " gdt-fg-r01-s01-p01\r\n"))["id"] == "p1"
    assert run(sr.position_by_barcode(db, "GD-L1-RAK")) is None


# ── 3. Universal Scan memakai SSOT + bentuk respons lama ─────────────────────
def test_universal_scan_fg_and_legacy_fields(monkeypatch):
    from routes import universal_scan as us
    db = seed_db()
    out = run(us._do_resolve(db, fg_qr_payload(), USER))
    assert out["found"] is True and out["entity_type"] == "fg" and out["tipe"] == "fg"
    assert out["entity_number"] == FG_SKU and out["sku"] == FG_SKU and "_doc" not in out
    assert out["quick_actions"][0]["module"] == "wh-fg"
    assert db.dewi_universal_scans.docs[-1]["found"] is True


@pytest.mark.parametrize("code,etype,module", [
    ("A-BIS-0001", "material", "wh-materials"),
    ("GDT-FG-R01-S01-P01", "bin", "wh-structure"),
    ("RL-202611-0001", "fabric_roll", "wms-fabric-rolls"),
])
def test_universal_scan_quick_action_modules_exist(code, etype, module):
    from routes import universal_scan as us
    out = run(us._do_resolve(seed_db(), code, USER))
    assert out["entity_type"] == etype and out["quick_actions"][0]["module"] == module
    reg_path = os.path.join(REPO, "frontend", "src", "components", "erp", "moduleRegistry.js")
    if os.path.exists(reg_path):   # modul tujuan aksi cepat harus benar-benar terdaftar di layar
        assert f"'{module}':" in open(reg_path, encoding="utf-8").read()


def test_universal_scan_unknown_logged_not_found():
    from routes import universal_scan as us
    db = seed_db()
    out = run(us._do_resolve(db, "  ZZZ-999 \r\n", USER))
    assert out == {"found": False, "raw_code": "ZZZ-999", "scan_id": out["scan_id"]}


# ── 4. opname3 memakai SSOT ──────────────────────────────────────────────────
def test_opname_resolve_item_and_bin_via_ssot():
    from routes import wms_opname3 as op
    db = seed_db()
    assert run(op._resolve_item(db, "", FG_SKU.lower()))["id"] == "fg1"
    assert run(op._resolve_item(db, "", fg_qr_payload()))["id"] == "fg1"
    assert run(op._resolve_item(db, "", "GDT-FG-R01-S01-P01")) is None     # bin bukan barang
    assert run(op._resolve_position(db, "", "gdt-fg-r01-s01-p01"))["id"] == "p1"
    assert run(op._resolve_position(db, "p1", ""))["id"] == "p1"


# ── 5. label: satu generator, isi Code128 benar ──────────────────────────────
def _decode_code128(values):
    """Dekoder Code128 mini atas codeword reportlab (start, data…, checksum, stop)."""
    assert values[-1] == 106, "stop"
    start, data, chk = values[0], values[1:-2], values[-2]
    assert (start + sum(i * v for i, v in enumerate(data, 1))) % 103 == chk, "checksum"
    mode = {103: "A", 104: "B", 105: "C"}[start]
    out = ""
    for v in data:
        if v == 99:
            mode = "C"
        elif v == 100:
            mode = "B"
        elif v == 101:
            mode = "A"
        elif mode == "C":
            out += f"{v:02d}"
        else:
            out += chr(v + 32)
    return out


@pytest.mark.parametrize("code", [FG_SKU, "A-BIS-0001", "KN-CND-DST 2", "RL-202611-0001",
                                  "GD-L1-ZN-FG-RK-01-S01-P01", "CUT-DA-1101-BRG-ALLSIZE"])
def test_code128_encodes_exact_code(code):
    b = lr._RLCode128(code, barWidth=1, quiet=False)
    b.validate()
    b.encode()
    assert _decode_code128(b.encoded) == code


class _Rec:
    drawn = []


def _recorder(monkeypatch):
    _Rec.drawn = []
    real = lr._RLCode128

    class Rec(real):
        def drawOn(self, canvas, x, y, *a, **k):
            _Rec.drawn.append((self.value, self.barWidth, self.lquiet, self.rquiet))
            return super().drawOn(canvas, x, y, *a, **k)
    monkeypatch.setattr(lr, "_RLCode128", Rec)


@pytest.mark.parametrize("kind,doc,expect_code", [
    ("fg", {"id": "fg1", "code": FG_SKU, "name": "Aisar"}, FG_SKU),
    ("material", {"id": "m1", "code": "A-BIS-0001", "name": "Bisban", "unit": "m"}, "A-BIS-0001"),
    ("bin", {"id": "p1", "barcode": "GD-L1-ZN-FG-RK-01-S01-P01", "label": "Shelf 1, Slot 1"},
     "GD-L1-ZN-FG-RK-01-S01-P01"),
    ("roll", {"id": "r1", "roll_no": "RL-202611-0001", "material_name": "Condru"}, "RL-202611-0001"),
])
def test_every_label_kind_uses_shared_vector_code128(monkeypatch, kind, doc, expect_code):
    _recorder(monkeypatch)
    pdf = lr.single_label_pdf(kind, doc).getvalue()
    assert pdf.startswith(b"%PDF")
    assert len(_Rec.drawn) == 1
    value, bw, lq, rq = _Rec.drawn[0]
    assert value == expect_code
    x_mm = bw / lr.mm
    assert lr.X_WARN_MM - 0.01 <= x_mm <= lr.X_MAX_MM + 1e-9, (kind, x_mm)
    assert abs(lq - 10 * bw) < 1e-6 and abs(rq - 10 * bw) < 1e-6      # quiet zone 10X


def test_bulk_labels_per_qty_and_fixed_bin_grid(monkeypatch):
    _recorder(monkeypatch)
    pages = []

    class C(lr.canvas.Canvas):
        def showPage(self):
            pages.append(1)
            return super().showPage()
    monkeypatch.setattr(lr.canvas, "Canvas", C)

    def n_pages(kind, docs):
        pages.clear()
        lr.grid_labels_pdf(kind, docs, footer=(kind == "bin"))
        return len(pages)            # canvas.save() menutup halaman terakhir lewat showPage
    fg = {"id": "fg1", "code": FG_SKU, "name": "Aisar"}
    assert n_pages("fg", [fg] * 8) == 1                         # FG 100×70 → 8/hal A4
    assert [d[0] for d in _Rec.drawn] == [FG_SKU] * 8           # 1 label per qty
    assert n_pages("fg", [fg] * 9) == 2
    bins = [{"id": f"p{i}", "barcode": f"GDT-FG-R01-S01-P{i:02d}"} for i in range(25)]
    assert n_pages("bin", bins[:24]) == 1                       # bin 3×8 = 24/hal (tetap)
    assert n_pages("bin", bins) == 2


@pytest.mark.parametrize("bad", ["", "   ", " DA-1 ", "KAOS-É", "A\tB", "X" * 41, None])
def test_invalid_codes_rejected_before_pdf(bad):
    with pytest.raises(lr.LabelCodeError):
        lr.validate_code(bad)


def test_no_more_na_barcode_for_missing_code():
    assert lr.code_of({"name": "tanpa kode"}) == ""
    with pytest.raises(lr.LabelCodeError):
        lr.single_label_pdf("fg", {"id": "x", "name": "tanpa kode"})
    with pytest.raises(lr.LabelCodeError):
        lr.grid_labels_pdf("material", [{"id": "a", "code": "OK-1"}, {"id": "b", "code": ""}])


def test_custom_fg_label_requires_master_sku(monkeypatch):
    from fastapi import HTTPException
    from routes import wms_fg_labels as wf
    db = seed_db()

    async def _auth(_req):
        return USER
    monkeypatch.setattr(wf, "require_auth", _auth)
    monkeypatch.setattr(wf, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(wf.custom_fg_label_pdf({"sku": "NGAWUR-123"}, None))
    assert e.value.status_code == 400
    resp = run(wf.custom_fg_label_pdf({"sku": FG_SKU.lower(), "batch_number": "B-7"}, None))
    assert resp.status_code == 200 and FG_SKU in resp.headers["content-disposition"]


# ── 6. skrip audit/pengisi SKU FG (dry-run) ──────────────────────────────────
def test_check_fg_barcodes_audit_pure():
    root_scripts = os.path.join(REPO, "scripts")
    if not os.path.exists(os.path.join(root_scripts, "check_fg_barcodes.py")):
        pytest.skip("folder scripts tidak ikut disalin")
    sys.path.insert(0, root_scripts)
    import check_fg_barcodes as cfb
    mats = [
        {"id": "a", "type": "fg", "code": "", "sku": "", "name": "Tanpa kode", "variant_id": "v9",
         "active": True},
        {"id": "b", "type": "fg", "code": "", "sku": "", "name": "Bentrok", "model_code": "DA-1",
         "color_code": "HTM", "size_code": "S", "active": True},
        {"id": "c", "type": "fg", "code": "DA-1-HTM-S", "sku": "DA-1-HTM-S", "active": True},
        {"id": "d", "type": "fabric", "code": "KN-CND-DST 2", "active": True},
        {"id": "e", "type": "accessory", "code": "da-1-htm-s", "active": True},
        {"id": "f", "type": "fg", "code": "DA-2-HTM-S", "sku": "DA-2-HTM-X", "active": True},
    ]
    res = cfb.audit(mats, [{"id": "v9", "sku": "da-9-htm-m"}])
    usul = {r["id"]: r for r in res["fg_tanpa_kode"]}
    assert usul["a"]["usulan"] == "DA-9-HTM-M" and usul["a"]["boleh_diterapkan"] is True
    assert usul["b"]["usulan"] == "DA-1-HTM-S" and usul["b"]["boleh_diterapkan"] is False   # bentrok
    assert [r["id"] for r in res["usulan"]] == ["a"]
    assert any(k["kode"] == "DA-1-HTM-S" for k in res["kode_kembar"])     # c vs e (beda huruf)
    assert [r["code"] for r in res["kode_berspasi"]] == ["KN-CND-DST 2"]
    assert [r["id"] for r in res["fg_code_ne_sku"]] == ["f"]
