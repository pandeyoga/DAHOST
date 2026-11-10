"""Uji unit HERMETIK Buat Barcode — cari & saring master + sumber "Dari penerimaan barang" (10 Nov 2026).

Permintaan owner: "pilih dari master tapi tidak bisa search dan tidak bisa filter ini akan sangat menyulitkan,
lalu harusnya bisa juga dari pembelian misal kain roll dll."

Angka harapan DIHITUNG TANGAN:
  * Master bahan aktif = 6 (M1–M5, M7; M6 nonaktif, F1 barang jadi). Kategori: Kain/Fabric = M1 + M2 (M2 hanya
    menyimpan id kategori → nama dari master kategori) = 2; Aksesoris = M3 + M4 + M7 = 3; tanpa kategori = M5 = 1.
  * Penerimaan GR-00007: kancing 120 pcs → 120 lembar; resleting 350 pcs (> 200) → 1; tali 2,5 pack (pecahan) → 1;
    karet 3 gross (hitungan) → 3; kain yard 2 roll (+1 roll batal tidak ikut) → 2 label roll; kain kg tanpa roll →
    pesan "Penerimaan tanpa roll"; baris tanpa master → tidak bisa dicetak; aset & baris ditolak semua → dilewati.
    Total lembar = 120 + 1 + 1 + 3 + 2 = 127.
  * Grid A4 90×50 mm: kolom = 210 // 90 = 2, baris = 297 // 50 = 5 → 10 label/halaman; 3 bahan + 8 roll = 11 → 2 halaman.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_barcode_cari_dari_pembelian.py -q
"""
import asyncio
import copy
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import label_render as lr  # noqa: E402
import routes.wms_barcode as wb  # noqa: E402

SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}
FE = os.path.join(ROOT, "frontend", "src", "components", "erp", "WMSBarcodeModule.jsx")
CAT_KAIN = "a6e79e66-6771-411b-ba70-7a0a078370d7"
CAT_AKS = "68c2b27c-7e3d-417c-aebf-438fd878070c"


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)


async def _sa(*_a, **_k):
    return SA


async def _noop(*_a, **_k):
    return None


async def _gen(*_a, **_k):
    return "BC-20261110-001"


def _db():
    db = fm.FakeDB()
    db.rahaza_material_categories.docs += [
        {"id": CAT_KAIN, "code": "FABRIC", "name": "Kain/Fabric", "active": True},
        {"id": CAT_AKS, "code": "ACCESSORY", "name": "Aksesoris", "active": True},
    ]
    db.rahaza_materials.docs += [
        {"id": "M1", "code": "KN-CND-HTM", "name": "Kain Condro Hitam", "type": "fabric", "unit": "yard",
         "category": CAT_KAIN, "category_name": "Kain/Fabric", "color": "Hitam", "active": True},
        # dokumen lama: hanya id kategori, tanpa nama → nama diambil dari master kategori
        {"id": "M2", "code": "KN-RYN-PTH", "name": "Kain Rayon Putih", "type": "fabric", "unit": "kg",
         "category": CAT_KAIN, "color": "Putih", "active": True},
        {"id": "M3", "code": "A-KCG-01", "name": "Kancing Kemeja", "type": "accessory", "unit": "pcs",
         "category": CAT_AKS, "category_name": "Aksesoris", "color": "Hitam", "active": True},
        {"id": "M4", "code": "A-RSL-20", "name": "Resleting 20 cm", "type": "accessory", "unit": "pcs",
         "category": CAT_AKS, "category_name": "Aksesoris", "active": True},
        {"id": "M5", "code": "B-TALI", "name": "Tali Rami", "type": "accessory", "unit": "pack", "active": True},
        {"id": "M6", "code": "A-LAMA", "name": "Kancing lama", "type": "accessory", "unit": "pcs",
         "category_name": "Aksesoris", "active": False},
        {"id": "M7", "code": "A-KARET", "name": "Karet Pinggang", "type": "accessory", "unit": "gross",
         "category_name": "Aksesoris", "active": True},
        {"id": "F1", "code": "DA-TS01-HTM-ALLSIZE", "name": "Kaos Hitam", "type": "fg", "unit": "pcs",
         "category": "Top", "category_name": "Top", "color_name": "Hitam", "active": True},
    ]
    return db


def _patch(monkeypatch, db):
    monkeypatch.setattr(wb, "require_auth", _sa)
    monkeypatch.setattr(wb, "get_db", lambda: db)
    monkeypatch.setattr(wb, "log_activity", _noop)
    monkeypatch.setattr(wb, "gen_prefixed_number", _gen)


def items(**kw):
    args = {"kind": "material", "q": "", "category": "", "color": "", "skip": 0, "limit": 60, **kw}
    return run(wb.barcode_items(Req(), **args))


# ═══════════════════════ 1. Cari & saring di "Pilih dari master" ═══════════════════════
def test_items_saring_kategori_warna_cari_dan_muat_bertahap(monkeypatch):
    db = _db()
    _patch(monkeypatch, db)
    semua = items()
    assert semua["total"] == 6 and not semua["has_more"]             # M6 nonaktif & F1 barang jadi tidak ikut
    cats = {c["value"]: c["count"] for c in semua["categories"]}
    assert cats == {"Aksesoris": 3, "Kain/Fabric": 2, wb.TANPA_KATEGORI: 1}
    assert all(not re.match(r"^[0-9a-f]{8}-", c["label"]) for c in semua["categories"])   # bukan id kategori
    assert semua["categories"][-1]["label"] == "Tanpa kategori"
    by_code = {it["code"]: it for it in semua["items"]}
    assert by_code["KN-RYN-PTH"]["category"] == "Kain/Fabric"                              # id → nama master

    kain = items(category="Kain/Fabric")
    assert [it["code"] for it in kain["items"]] == ["KN-CND-HTM", "KN-RYN-PTH"] and kain["total"] == 2
    assert {c["value"] for c in kain["colors"]} == {"Hitam", "Putih"}                     # warna ikut kategori
    assert {c["value"] for c in kain["categories"]} >= {"Aksesoris", "Kain/Fabric"}       # pilihan kategori tetap
    assert [it["code"] for it in items(category="Kain/Fabric", color="Hitam")["items"]] == ["KN-CND-HTM"]
    assert [it["code"] for it in items(category=wb.TANPA_KATEGORI)["items"]] == ["B-TALI"]
    assert [it["code"] for it in items(q="resleting")["items"]] == ["A-RSL-20"]           # cari nama
    assert [it["code"] for it in items(q="kcg", category="Aksesoris")["items"]] == ["A-KCG-01"]

    # muat bertahap: tidak berhenti di batas pertama
    p1 = items(limit=4)
    assert p1["returned"] == 4 and p1["has_more"] and p1["total"] == 6
    p2 = items(limit=4, skip=4)
    assert p2["returned"] == 2 and not p2["has_more"]
    assert len({it["id"] for it in p1["items"] + p2["items"]}) == 6

    fg = items(kind="fg")
    assert [it["code"] for it in fg["items"]] == ["DA-TS01-HTM-ALLSIZE"]
    assert fg["categories"] == [{"value": "Top", "label": "Top", "count": 1}]


# ═══════════════════════ 2. Dari penerimaan barang ═══════════════════════
def _gr_db():
    db = _db()
    line = lambda i, mid, qty, unit: {"id": i, "material_id": mid, "sku": "", "product_name": "",  # noqa: E731
                                      "received_qty": qty, "rejected_qty": 0, "accepted_qty": qty, "unit": unit}
    db.warehouse_receiving.docs += [
        {"id": "GR7", "receipt_number": "GR-00007", "status": "received", "supplier_name": "PT Sumber Kain",
         "po_number": "PO-2026-0012", "created_at": "2026-11-09T02:00:00+00:00",
         "received_at": "2026-11-09T03:00:00+00:00", "items": [
             line("L1", "M3", 120, "pcs"),
             line("L2", "M4", 350, "pcs"),
             line("L3", "M5", 2.5, "pack"),
             line("L4", "M7", 3, "gross"),
             line("L5", "M1", 200, "yard"),
             line("L6", "M2", 50, "kg"),
             {"id": "L7", "material_id": None, "sku": "", "product_name": "Benang bebas", "received_qty": 5,
              "accepted_qty": 5, "unit": "pcs"},
             {"id": "L8", "material_id": None, "product_name": "Mesin obras", "item_type": "asset",
              "received_qty": 1, "accepted_qty": 1, "unit": "unit"},
             {"id": "L9", "material_id": "M3", "received_qty": 10, "rejected_qty": 10, "accepted_qty": 0,
              "unit": "pcs"},
         ]},
        {"id": "GR8", "receipt_number": "GR-00008", "status": "draft", "supplier_name": "CV Kancing",
         "created_at": "2026-11-10T02:00:00+00:00", "items": []},
    ]
    roll = lambda i, no, qty, **kw: {"id": i, "roll_no": no, "material_id": "M1", "material_code": "KN-CND-HTM",  # noqa: E731
                                    "material_name": "Kain Condro Hitam", "color": "Hitam", "color_lot": "LOT-A",
                                    "supplier_name": "PT Sumber Kain", "uom": "yard", "length_m": qty,
                                    "remaining_m": qty, "weight_kg": 0.0, "remaining_kg": 0.0, "status": "in_stock",
                                    "source_receipt_id": "GR7", "source_receipt_number": "GR-00007",
                                    "source_receipt_item_id": "L5", **kw}
    db.wh_fabric_rolls.docs += [
        roll("R1", "RL-202611-0001", 100.0),
        roll("R2", "RL-202611-0002", 100.0, remaining_m=40.0, status="partly_issued"),
        roll("R3", "RL-202611-0003", 0.0, status="cancelled"),
    ]
    return db


def test_dari_penerimaan_bahan_hitungan_roll_kain_dan_kain_tanpa_roll(monkeypatch):
    db = _gr_db()
    _patch(monkeypatch, db)
    opts = run(wb.receipt_options(Req(), limit=100))
    assert [o["receipt_number"] for o in opts] == ["GR-00007"]                       # draf tidak bisa dipilih
    o = opts[0]
    assert (o["supplier_name"], o["po_number"], o["roll_count"], o["item_count"]) == (
        "PT Sumber Kain", "PO-2026-0012", 2, 9)
    assert o["received_at"].startswith("2026-11-09T03")

    d = run(wb.from_receipt(Req(), receipt_id="GR7"))
    mats = {r["code"]: r for r in d["rows"] if r["label_kind"] == "material" and r["master_linked"]}
    assert {c: r["copies"] for c, r in mats.items()} == {"A-KCG-01": 120, "A-RSL-20": 1, "B-TALI": 1, "A-KARET": 3}
    assert mats["A-KCG-01"]["category"] == "Aksesoris" and mats["A-KCG-01"]["qty_received"] == 120
    rolls = [r for r in d["rows"] if r["label_kind"] == "roll"]
    assert [r["code"] for r in rolls] == ["RL-202611-0001", "RL-202611-0002"]           # roll batal tidak ikut
    assert rolls[1]["qty_remaining"] == 40.0 and rolls[1]["unit"] == "yard" and rolls[1]["copies"] == 1
    assert "KN-CND-HTM" not in mats                                                     # kain → label roll, bukan bahan
    # kain kg tanpa roll → tidak dicetak, diarahkan ke Roll Kain › Penerimaan tanpa roll
    assert [f["material_code"] for f in d["fabric_without_rolls"]] == ["KN-RYN-PTH"]
    assert d["fabric_without_rolls"][0]["accepted_qty"] == 50
    assert "Penerimaan tanpa roll" in d["message"] and "Roll Kain" in d["message"]
    unl = [r for r in d["rows"] if r["master_linked"] is False]
    assert len(unl) == 1 and unl[0]["name"] == "Benang bebas" and "master" in unl[0]["reason"]
    assert {s["reason"].split(" ")[0] for s in d["skipped"]} == {"Barang", "Seluruh"}   # aset + ditolak semua
    assert (d["material_count"], d["roll_count"], d["unlinked_count"]) == (4, 2, 1)
    assert d["total_copies"] == 127 and d["receipt_number"] == "GR-00007"

    with pytest.raises(HTTPException) as e:
        run(wb.from_receipt(Req(), receipt_id="GR8"))
    assert e.value.status_code == 400 and "belum selesai diterima" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(wb.from_receipt(Req(), receipt_id="TIDAK-ADA"))
    assert e.value.status_code == 404


def test_lembar_bawaan_hanya_satuan_hitungan_bulat_maks_200():
    assert wb.default_copies(120, "pcs") == 120
    assert wb.default_copies(200, "Lusin") == 200
    assert wb.default_copies(201, "pcs") == 1
    assert wb.default_copies(2.5, "pack") == 1
    assert wb.default_copies(25, "kg") == 1 and wb.default_copies(30, "yard") == 1
    assert wb.default_copies(0, "pcs") == 1


# ═══════════════════════ 3. Cetak batch: bahan + label roll dalam satu PDF ═══════════════════════
class _Rec:
    drawn: list = []
    pages: list = []


def _record(monkeypatch):
    _Rec.drawn, _Rec.pages = [], []
    real = lr._RLCode128

    class Rec(real):
        def drawOn(self, canvas, x, y, *a, **k):
            _Rec.drawn.append(self.value)
            return super().drawOn(canvas, x, y, *a, **k)
    monkeypatch.setattr(lr, "_RLCode128", Rec)

    class C(lr.canvas.Canvas):
        def showPage(self):
            _Rec.pages.append(1)
            return super().showPage()
    monkeypatch.setattr(lr.canvas, "Canvas", C)


def test_batch_pdf_bahan_dan_roll_satu_pdf_tercatat_dari_pembelian(monkeypatch):
    db = _gr_db()
    _patch(monkeypatch, db)
    _record(monkeypatch)
    seen = {}
    real_mixed = lr.grid_labels_pdf_mixed

    def mixed(entries, **kw):
        seen["entries"] = list(entries)
        return real_mixed(seen["entries"], **kw)
    monkeypatch.setattr(wb.lr, "grid_labels_pdf_mixed", mixed)

    body = wb.BarcodeBatchIn(
        kind="material", source="pembelian", receipt_id="GR7", include_stock=False,
        rows=[{"id": "M3", "code": "A-KCG-01", "copies": 3}],
        rolls=[{"id": "R1", "roll_no": "RL-202611-0001", "copies": 4},
               {"roll_no": "RL-202611-0002", "copies": 4}])
    res = run(wb.barcode_batch_pdf(body, Req()))
    assert res.headers["X-Barcode-Labels"] == "11"
    kinds = [k for k, _ in seen["entries"]]
    assert kinds == ["material"] * 3 + ["roll"] * 8
    assert _Rec.drawn == ["A-KCG-01"] * 3 + ["RL-202611-0001"] * 4 + ["RL-202611-0002"] * 4
    assert len(_Rec.pages) == 2                                     # 10 label/halaman A4 → 11 label = 2 halaman
    mat_doc = seen["entries"][0][1]
    assert mat_doc["category"] == "Aksesoris"                       # nama kategori di label, bukan id kategori
    roll_doc = seen["entries"][-1][1]
    assert roll_doc["qty_text"] == "Qty: 100.00 yard · sisa 40.00 yard"
    job = db.wh_barcode_print_jobs.docs[0]
    assert (job["source"], job["receipt_id"], job["receipt_number"]) == ("pembelian", "GR7", "GR-00007")
    assert (job["total_labels"], job["roll_labels"], job["item_count"]) == (11, 8, 3)
    assert [r["roll_no"] for r in job["rolls"]] == ["RL-202611-0001", "RL-202611-0002"]


def test_batch_pdf_roll_ditolak_bila_salah_jenis_tidak_ada_atau_batal(monkeypatch):
    db = _gr_db()
    _patch(monkeypatch, db)
    cases = [
        (dict(kind="fg", rolls=[{"roll_no": "RL-202611-0001"}]), "hanya bisa dicetak di jenis Bahan"),
        (dict(kind="material", rolls=[{"roll_no": "RL-KARANGAN-9"}]), "tidak ditemukan"),
        (dict(kind="material", rolls=[{"id": "R3"}]), "sudah dibatalkan"),
        (dict(kind="material", rows=[], rolls=[]), "Belum ada item"),
    ]
    for kw, pesan in cases:
        with pytest.raises(HTTPException) as e:
            run(wb.barcode_batch_pdf(wb.BarcodeBatchIn(**kw), Req()))
        assert e.value.status_code == 400 and pesan in e.value.detail, kw
    assert db.wh_barcode_print_jobs.docs == []                      # gagal = tidak tercatat di riwayat


def test_sumber_tak_dikenal_dicatat_manual_dan_alur_lama_tetap(monkeypatch):
    db = _db()
    _patch(monkeypatch, db)
    calls = []

    def grid(kind, docs, **kw):
        calls.append((kind, [d.get("category") for d in docs]))
        import io
        return io.BytesIO(b"%PDF-uji")
    monkeypatch.setattr(wb.lr, "grid_labels_pdf", grid)
    run(wb.barcode_batch_pdf(wb.BarcodeBatchIn(kind="material", source="karangan", include_stock=False,
                                               rows=[{"code": "KN-RYN-PTH", "copies": 2}]), Req()))
    assert calls == [("material", ["Kain/Fabric", "Kain/Fabric"])]  # tanpa roll → grid satu jenis (alur lama)
    assert db.wh_barcode_print_jobs.docs[0]["source"] == "manual"
    assert db.rahaza_materials.docs[1]["category"] == CAT_KAIN      # master tidak diubah


def test_grid_campuran_hanya_untuk_label_seukuran():
    roll = {"id": "r", "roll_no": "RL-202611-0001", "material_name": "Kain"}
    mat = {"id": "m", "code": "A-KCG-01", "name": "Kancing"}
    assert lr.grid_labels_pdf_mixed([("material", mat), ("roll", roll)]).getvalue().startswith(b"%PDF")
    with pytest.raises(ValueError):
        lr.grid_labels_pdf_mixed([("material", mat), ("fg", {"code": "DA-1"})])          # 90×50 vs 100×70
    with pytest.raises(ValueError):
        lr.grid_labels_pdf_mixed([])
    with pytest.raises(lr.LabelCodeError):
        lr.grid_labels_pdf_mixed([("material", mat), ("roll", {"id": "x", "roll_no": ""})])


def test_format_qty_label_roll_sama_dengan_label_roll_satuan():
    """Label roll di Buat Barcode = label roll satuan (Roll Kain): baris qty ditulis dengan format yang sama."""
    fmt = "f\"Qty: {v['qty_total']:,.2f} {unit} · sisa {v['qty_remaining']:,.2f} {unit}\""
    for rel in ("routes/wms_barcode.py", "routes/wms_fabric_rolls.py"):
        with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
            assert fmt in f.read(), rel


# ═══════════════════════ 4. Layar ═══════════════════════
def test_layar_cari_di_kartu_master_penyaring_dan_sumber_pembelian():
    src = open(FE, encoding="utf-8").read()
    # kotak cari ada SATU, di kartu "Pilih dari master" (bukan di slot penyaring halaman)
    assert src.count('data-testid="barcode-search-input"') == 1
    i_kartu, i_cari, i_tabel = (src.index("Pilih dari master</p>"), src.index('data-testid="barcode-search-input"'),
                                src.index('testId="barcode-items-table"'))
    assert i_kartu < i_cari < i_tabel
    filters_slot = src[src.index("filters={"):src.index("tools={")]
    assert "barcode-search-input" not in filters_slot
    for s in ('data-testid="barcode-category-filter"', 'data-testid="barcode-color-filter"', "Semua kategori",
              "Tampilkan lebih banyak", "Tambah semua yang tampil", "&skip=${skip}",
              "Otomatis dari penerimaan barang", "/wms/barcode/receipt-options?limit=100",
              "/wms/barcode/from-receipt?receipt_id=", "Ambil barang & jumlahnya",
              "source: receiptInfo ? 'pembelian'", "receipt_id: receiptInfo?.receipt_id",
              "'Dari pembelian'", "rolls: bisaDicetak.filter(r => r.label_kind === 'roll')",
              'testId="barcode-receipt-no-roll"'):
        assert s in src, s
    assert "limit=60" not in src and "persempit dengan pencarian" not in src
    # pilihan tetap SmartNativeSelect (tanpa <select> polos), tanpa kotak kode ketikan bebas
    assert not re.search(r"^\s*<(select|table|input)\b", src, re.M)
