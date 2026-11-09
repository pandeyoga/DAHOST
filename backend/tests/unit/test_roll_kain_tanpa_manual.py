"""Roll Kain tanpa input manual + put-away dari master struktur gudang (keputusan owner 10 Nov 2026) — hermetik.

Pertanyaan owner: kenapa roll bisa diinput manual dan isiannya tidak dari master? Faktanya roll manual
(`POST /api/wms/fabric-rolls`) berstatus Tersedia TANPA menambah stok bahan dan TANPA jurnal ⇒ roll tanpa stok
atau roll dobel. Yang dikunci di sini:
  * POST manual → 410 dengan kalimat staf yang menyebut tiga jalur resmi (Penerimaan Barang › rincian gulungan,
    "Penerimaan tanpa roll", Impor roll stok awal); tidak ada roll yang tertulis;
  * put-away hanya ke posisi yang ADA di master (`wh_positions`, rak/zona/gudang aktif) — id tak dikenal,
    barcode tak dikenal, id ≠ barcode, rak nonaktif, roll dibatalkan → ditolak; barcode scan disimpan sebagai
    kode baku master;
  * roll dari penerimaan tidak lagi menaruh id LOKASI di `position_id` (itu id posisi rak);
  * sumber layar: tak ada tombol/popup roll manual; put-away memakai pemilih bertingkat + pemindai bersama.
"""
import asyncio
import inspect
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
ERP = REPO / "frontend" / "src" / "components" / "erp"
GUDANG = {"id": "u-gd", "name": "Admin Gudang", "role": "admin_gudang"}


def run(c):
    return asyncio.run(c)


def fe(rel: str) -> str:
    p = ERP / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


async def _auth(*_a, **_k):
    return GUDANG


@pytest.fixture
def wfr(monkeypatch):
    import routes.wms_fabric_rolls as mod
    db = fm.FakeDB()
    db.wh_buildings.docs.append({"id": "b1", "code": "GD1", "name": "Gudang Kain", "active": True})
    db.wh_zones.docs.append({"id": "z1", "building_id": "b1", "code": "KN", "name": "Zona kain", "active": True})
    db.wh_racks.docs += [
        {"id": "r1", "zone_id": "z1", "building_id": "b1", "code": "R01", "name": "Rak 1", "active": True},
        {"id": "r2", "zone_id": "z1", "building_id": "b1", "code": "R02", "name": "Rak 2", "active": False},
    ]
    db.wh_positions.docs += [
        {"id": "p1", "rack_id": "r1", "zone_id": "z1", "building_id": "b1", "building_code": "GD1",
         "zone_code": "KN", "rack_code": "R01", "shelf_no": 1, "slot_no": 2, "barcode": "GD1-KN-R01-S01-P02"},
        {"id": "p2", "rack_id": "r2", "zone_id": "z1", "building_id": "b1", "building_code": "GD1",
         "zone_code": "KN", "rack_code": "R02", "shelf_no": 1, "slot_no": 1, "barcode": "GD1-KN-R02-S01-P01"},
    ]
    db.wh_fabric_rolls.docs += [
        {"id": "rl1", "roll_no": "RL-202611-0001", "uom": "yard", "status": "in_stock", "length_m": 97.5,
         "remaining_m": 97.5, "position_id": "", "position_barcode": "", "location_id": "loc-kain"},
        {"id": "rl2", "roll_no": "RL-202611-0002", "uom": "kg", "status": "cancelled", "weight_kg": 25.0,
         "remaining_kg": 25.0, "position_id": "", "position_barcode": ""},
    ]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "require_auth", _auth)
    mod._db = db
    return mod


def _tolak(coro, kode=400):
    with pytest.raises(HTTPException) as e:
        run(coro)
    assert e.value.status_code == kode, e.value.detail
    return str(e.value.detail)


# ── 1. Input roll manual ditutup ─────────────────────────────────────────────────────────────────────

def test_post_roll_manual_ditolak_410_dengan_tiga_jalur_resmi(wfr):
    pesan = _tolak(wfr.create_roll(fm.FakeRequest({
        "material_id": "m1", "material_code": "KN-01", "material_name": "Cotton", "length_m": 100})), 410)
    for jalur in ("Penerimaan Barang", "rincian gulungan", "Penerimaan tanpa roll", "Impor roll stok awal"):
        assert jalur in pesan
    assert "stok" in pesan and "jurnal" in pesan
    assert len(wfr._db.wh_fabric_rolls.docs) == 2 and wfr._db.wh_fabric_roll_movements.docs == []


def test_post_roll_manual_tidak_membaca_isian_dan_jalur_lama_hilang():
    import routes.wms_fabric_rolls as mod
    from core import fabric_roll_engine as fre
    # Body tidak dibaca ⇒ isian apa pun dijawab 410 (bukan 422), dan tidak ada model/nomor roll ketikan lagi.
    assert list(inspect.signature(mod.create_roll).parameters) == ["request"]
    assert not hasattr(mod, "RollIn") and not hasattr(fre, "issue_roll_no")
    rute = [r for r in mod.router.routes if getattr(r, "path", "") == "/api/wms/fabric-rolls"
            and "POST" in getattr(r, "methods", set())]
    assert len(rute) == 1 and rute[0].endpoint is mod.create_roll


# ── 2. Put-away hanya ke posisi di master struktur gudang ────────────────────────────────────────────

def test_putaway_posisi_tak_dikenal_ditolak(wfr):
    p = wfr.PutAwayIn
    assert "master struktur gudang" in _tolak(wfr.putaway_roll("rl1", p(position_id="ngarang"), fm.FakeRequest()))
    assert "tidak dikenal" in _tolak(wfr.putaway_roll("rl1", p(position_barcode="RAK-KARANGAN"), fm.FakeRequest()))
    assert "Pilih posisi" in _tolak(wfr.putaway_roll("rl1", p(), fm.FakeRequest()))
    assert "bukan milik" in _tolak(wfr.putaway_roll(
        "rl1", p(position_id="p1", position_barcode="GD1-KN-R02-S01-P01"), fm.FakeRequest()))
    roll = wfr._db.wh_fabric_rolls.docs[0]
    assert roll["position_id"] == "" and roll["position_barcode"] == ""
    assert wfr._db.wh_fabric_roll_movements.docs == []


def test_putaway_rak_nonaktif_dan_roll_dibatalkan_ditolak(wfr):
    p = wfr.PutAwayIn
    assert "Rak" in _tolak(wfr.putaway_roll("rl1", p(position_id="p2"), fm.FakeRequest()))
    wfr._db.wh_zones.docs[0]["active"] = False
    assert "Zona" in _tolak(wfr.putaway_roll("rl1", p(position_id="p1"), fm.FakeRequest()))
    wfr._db.wh_zones.docs[0]["active"] = True
    assert "dibatalkan" in _tolak(wfr.putaway_roll("rl2", p(position_id="p1"), fm.FakeRequest()))
    assert wfr._db.wh_fabric_roll_movements.docs == []


def test_putaway_dari_pilihan_master(wfr):
    out = run(wfr.putaway_roll("rl1", wfr.PutAwayIn(position_id="p1", position_barcode="GD1-KN-R01-S01-P02"),
                               fm.FakeRequest()))
    assert out == {"ok": True, "position_id": "p1", "position_barcode": "GD1-KN-R01-S01-P02"}
    roll = wfr._db.wh_fabric_rolls.docs[0]
    assert (roll["position_id"], roll["position_barcode"]) == ("p1", "GD1-KN-R01-S01-P02")
    (mov,) = wfr._db.wh_fabric_roll_movements.docs
    assert mov["movement_type"] == "putaway" and mov["to_location"] == "GD1-KN-R01-S01-P02"


def test_putaway_dari_scan_disimpan_sebagai_kode_baku(wfr):
    # Scan mentah (huruf kecil + enter dari pemindai) dicocokkan lewat SSOT kode scan; yang disimpan kode master.
    out = run(wfr.putaway_roll("rl1", wfr.PutAwayIn(position_barcode=" gd1-kn-r01-s01-p02\r\n"), fm.FakeRequest()))
    assert out["position_id"] == "p1" and out["position_barcode"] == "GD1-KN-R01-S01-P02"
    assert wfr._db.wh_fabric_rolls.docs[0]["position_barcode"] == "GD1-KN-R01-S01-P02"


# ── 3. Roll dari penerimaan: position_id bukan id lokasi ─────────────────────────────────────────────

def test_roll_dari_penerimaan_tidak_menaruh_lokasi_di_position_id(monkeypatch):
    from core import fabric_roll_engine as fre
    db = fm.FakeDB()
    nomor = iter(["RL-202611-0101", "RL-202611-0102"])

    async def _next(_db):
        return next(nomor)
    monkeypatch.setattr(fre, "next_roll_no", _next)
    gr = {"id": "gr1", "receipt_number": "GR-0001", "location_id": "loc-kain", "location_name": "Gudang Kain",
          "supplier_name": "PT Kain", "created_at": "2026-11-10T08:00:00+00:00"}
    item = {"id": "it1", "inspection_status": "passed", "unit_price": 20000}
    mat = {"id": "m1", "code": "KN-01", "name": "Cotton", "unit": "yard"}
    made = run(fre.create_rolls_from_receipt(db, gr, item, mat, [{"qty": 50.0}, {"qty": 47.5}], GUDANG))
    assert [r["roll_no"] for r in made] == ["RL-202611-0101", "RL-202611-0102"]
    for r in db.wh_fabric_rolls.docs:
        assert r["position_id"] == "" and r["position_barcode"] == "" and r["location_id"] == "loc-kain"


# ── 4. Sumber layar ──────────────────────────────────────────────────────────────────────────────────

def test_layar_roll_kain_tanpa_input_manual():
    s = fe("WMSFabricRollsModule.jsx")
    for dilarang in ("Roll baru", "Buat roll manual", "create-roll-btn", "create-roll-dialog", "handleCreateRoll",
                     "createPick", "input-position-id", "input-position-barcode", "ID posisi"):
        assert dilarang not in s, dilarang
    # Satu-satunya POST ke daftar roll dulu = buat manual; kini tidak ada lagi.
    assert "fabric-rolls`, {" not in s
    # Tampilan kosong menjelaskan tiga jalur resmi.
    for jalur in ("Penerimaan Barang", "rincian gulungan", "Penerimaan tanpa roll", "Impor roll stok awal"):
        assert jalur in s, jalur
    assert "<RollPutawayPopup" in s


def test_put_away_memilih_posisi_bertingkat_atau_scan():
    p = fe("warehouse/RollPutawayPopup.jsx")
    for url in ("/api/wms/buildings", "/api/wms/zones?building_id=", "/api/wms/racks?zone_id=",
                "/api/wms/positions?rack_id=", "/api/wms/positions/by-barcode/"):
        assert url in p, url
    for tid in ("putaway-building-select", "putaway-zone-select", "putaway-rack-select", "putaway-position-select"):
        assert f'data-testid="{tid}"' in p, tid
    assert "<UniversalScanner" in p and "<SmartNativeSelect" in p
    assert "<select" not in p and "<button" not in p and "window.confirm" not in p
    # Posisi tidak diketik: satu-satunya <Input> di popup ini adalah Catatan.
    assert p.count("<Input ") == 1 and 'id="pa-roll-catatan"' in p
