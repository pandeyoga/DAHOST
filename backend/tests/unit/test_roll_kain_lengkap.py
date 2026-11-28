"""Uji unit HERMETIK — stok kain = isi gulungannya (owner 28 Nov 2026: "Ya, perbaiki").

Sesudah cutoff kain 27 Nov (stok kain = Σ sisa roll), jalur yang dulu hanya mengubah kg/yard kini ikut mengubah roll:
  1. Opname kain per roll — scan label roll (isi hasil timbang; kosong = sesuai catatan), kode kain = roll tanpa label;
     saat disetujui roll yang dihitung disesuaikan, roll yang tidak ditemukan ditutup, roll tanpa label terbit.
  2. Penyesuaian kain — kurang wajib menunjuk roll + jumlah per roll; tambah menerbitkan roll.
  3. Pindah lokasi kain — roll utuh, Σ sisa = qty; Surat Jalan internal menolak kain.
  4. Penerimaan kain wajib rincian gulungan.

Angka dihitung tangan (lihat tiap uji). Jalankan:  cd backend && python -m pytest tests/unit/test_roll_kain_lengkap.py -q
"""
import asyncio
import inspect
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_k9_opname_engine import DB, env, seed, _flow, at  # noqa: E402,F401  (Mongo palsu + fixture mesin opname)
from core import fabric_roll_engine as fre  # noqa: E402
from core import opname_engine as eng  # noqa: E402
from core import stock_service  # noqa: E402

USER = {"id": "u-gd", "name": "Admin Gudang", "role": "superadmin"}
REPO = Path(__file__).resolve().parents[3]
ERP = REPO / "frontend" / "src" / "components" / "erp"


def run(c):
    return asyncio.run(c)


def fe(rel):
    p = ERP / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


@pytest.fixture
def db(monkeypatch):
    d = DB()
    n = {"i": 0}

    async def nomor(_db):
        n["i"] += 1
        return f"RL-UJI-{n['i']:03d}"
    monkeypatch.setattr(fre, "next_roll_no", nomor)
    d.rahaza_locations.docs += [{"id": "L1", "code": "GD-L2-CUT", "name": "Area Cutting"},
                                {"id": "L2", "code": "GD-L1", "name": "Gudang Lantai 1"}]
    d.rahaza_materials.docs += [
        {"id": "M1", "code": "KN-K31-GRY", "name": "RIB KNIT 31", "type": "fabric", "unit": "kg", "unit_cost": 47500.0},
        {"id": "M2", "code": "KN-K31-BLU", "name": "RIB KNIT 31", "type": "fabric", "unit": "kg", "unit_cost": 47500.0},
        {"id": "AC", "code": "A-KCG", "name": "Kancing", "type": "accessory", "unit": "pcs", "unit_cost": 500.0}]
    d.wh_fabric_rolls.docs += [
        {"id": "R1", "roll_no": "RL-1", "material_id": "M1", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 25.0,
         "status": "in_stock", "location_id": "L1", "location_name": "Area Cutting", "position_id": "P9",
         "position_barcode": "B9"},
        {"id": "R2", "roll_no": "RL-2", "material_id": "M1", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 20.0,
         "status": "partly_issued", "location_id": "L1"},
        {"id": "R3", "roll_no": "RL-3", "material_id": "M1", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 10.0,
         "status": "partly_issued", "location_id": "L1"},
        {"id": "R4", "roll_no": "RL-4", "material_id": "M2", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 25.0,
         "status": "in_stock", "location_id": "L1"}]
    return d


def roll(db, rid):
    return next(r for r in db.wh_fabric_rolls.docs if r["id"] == rid)


def _sess(db, **kw):
    s = {"id": "S1", "session_no": "OPN-UJI-1", "engine": eng.ENGINE, "status": "counting", "level": "lokasi",
         "location_id": "L1", "location_ids": ["L1"], "lines": [], "kinds": [], "material_ids": [], **kw}
    db[eng.SESS].docs.append(s)
    return s


async def _sess_now(db):
    return await eng.get_session(db, "S1")


# ═════════════════════ 1. OPNAME KAIN PER ROLL ═════════════════════
def test_per_roll_hanya_kain():
    assert fre.per_roll({"type": "fabric", "unit": "kg"}) and fre.per_roll({"type": "fabric", "unit": "yard"})
    assert not fre.per_roll({"type": "accessory", "unit": "kg"})       # benang kiloan: belum punya roll
    assert not fre.per_roll({"type": "fabric", "unit": "pcs"}) and not fre.per_roll(None)


def test_hitung_roll_berlabel_tanpa_label_dan_koreksi(db):
    s = _sess(db)
    m1 = db.rahaza_materials.docs[0]
    # RL-1 ditimbang 24,5; RL-2 tidak ditimbang (sesuai catatan 20); scan ulang RL-1 = 25 → 25 + 20 = 45
    run(eng.record_roll_count(db, USER, s, roll=roll(db, "R1"), bin_id="", bin_label="lantai", qty=24.5))
    out = run(eng.record_roll_count(db, USER, run(_sess_now(db)), roll=roll(db, "R2"), bin_id="", bin_label="lantai",
                                    qty=None))
    assert out["counted_qty"] == 44.5 and out["pakai_catatan"] is True and out["roll_qty"] == 20.0
    out = run(eng.record_roll_count(db, USER, run(_sess_now(db)), roll=roll(db, "R1"), bin_id="", bin_label="lantai",
                                    qty=25))
    assert out["counted_qty"] == 45.0
    cnt = db[eng.CNT].docs[0]
    assert [x["roll_no"] for x in cnt["rolls"]] == ["RL-2", "RL-1"] and cnt["rolls"][1]["remaining_at_count"] == 25.0
    # kode kain tanpa isi roll → ditolak; dengan isi 12 → satu roll tanpa label → 57
    with pytest.raises(HTTPException) as e:
        run(eng.record_count(db, USER, run(_sess_now(db)), mat=m1, bin_id="", bin_label="lantai", qty=1))
    assert e.value.status_code == 400 and "per roll" in e.value.detail
    out = run(eng.record_count(db, USER, run(_sess_now(db)), mat=m1, bin_id="", bin_label="lantai", qty=1,
                               roll_qty=12))
    assert out["counted_qty"] == 57.0 and out["tanpa_label"] is True
    # hapus roll tanpa label → 45; hapus RL-2 → 25
    run(eng.remove_roll_entry(db, USER, run(_sess_now(db)), mat=m1, bin_id="", baru_index=0))
    out = run(eng.remove_roll_entry(db, USER, run(_sess_now(db)), mat=m1, bin_id="", roll_id="R2"))
    assert out["counted_qty"] == 25.0
    # baris opname kain dibuat sekali
    assert [ln["material_id"] for ln in run(_sess_now(db))["lines"]] == ["M1"]


def test_hitung_buta_menyembunyikan_sisa_roll_tercatat(db):
    s = _sess(db)
    run(eng.record_roll_count(db, USER, s, roll=roll(db, "R1"), bin_id="", bin_label="lantai", qty=24.5))
    view = run(eng.session_view(db, run(_sess_now(db))))
    ent = view["lines"][0]["entries"][0]
    assert ent["per_roll"] and ent["rolls"][0]["roll_no"] == "RL-1"
    assert "remaining_at_count" not in ent["rolls"][0] and "system_qty" not in view["lines"][0]


def test_hitung_rak_dan_impor_roll_tetap_cara_lama(db):
    assert not eng.hitung_per_roll({"level": "rak"}, db.rahaza_materials.docs[0])
    assert not eng.hitung_per_roll({"level": "lokasi", "roll_import_id": "imp"}, db.rahaza_materials.docs[0])
    assert eng.hitung_per_roll({"level": "lokasi"}, db.rahaza_materials.docs[0])
    with pytest.raises(HTTPException):
        run(eng.record_roll_count(db, USER, _sess(db, level="rak"), roll=roll(db, "R1"), bin_id="B", bin_label="b",
                                  qty=1))


def test_sinkron_roll_saat_disetujui(db):
    """M1: RL-1 dihitung 24,5 (catatan saat scan 25); RL-2 dihitung sesuai catatan 20, lalu dipotong 5 SESUDAH di-scan
    (sisa kini 15) → 15 + 20 − 20 = 15; RL-3 tidak ditemukan → ditutup; roll tanpa label 12 → roll baru di L1.
    M2: "anggap 0" → RL-4 ditutup. Σ roll M1 sesudahnya = 24,5 + 15 + 12 = 51,5 (= hitung 56,5 − pemakaian 5)."""
    s = _sess(db)
    roll(db, "R2")["remaining_kg"] = 15.0                     # cutting sesudah di-scan
    ev = {"lines": [
        {"key": "M1", "material_id": "M1", "material_code": "KN-K31-GRY", "unit_cost": 47500.0, "entries": [
            {"bin_id": "", "per_roll": True, "counted_qty": 56.5,
             "rolls": [{"roll_id": "R1", "roll_no": "RL-1", "qty": 24.5, "remaining_at_count": 25.0},
                       {"roll_id": "R2", "roll_no": "RL-2", "qty": 20.0, "remaining_at_count": 20.0,
                        "pakai_catatan": True}],
             "rolls_baru": [{"qty": 12.0}]}]},
        {"key": "M2", "material_id": "M2", "material_code": "KN-K31-BLU", "unit_cost": 47500.0, "entries": []},
        {"key": "AC", "material_id": "AC", "material_code": "A-KCG", "entries": [{"counted_qty": 5}]}]}
    meta = {m["id"]: m for m in db.rahaza_materials.docs}
    locs = {"L1": {"id": "L1", "code": "GD-L2-CUT", "name": "Area Cutting"}}
    hasil = run(eng._sinkron_roll(db, USER, s, ev, meta, default_home="L1", pos_zone={}, loc_docs=locs))
    assert hasil == {"disesuaikan": 2, "ditutup": 2, "baru": 1, "tanpa_rincian_roll": []}
    assert roll(db, "R1")["remaining_kg"] == 24.5 and roll(db, "R1")["status"] == "partly_issued"
    assert roll(db, "R2")["remaining_kg"] == 15.0
    assert roll(db, "R3")["status"] == "cancelled" and roll(db, "R3")["remaining_kg"] == 0.0
    assert "Tidak ditemukan saat opname OPN-UJI-1" in roll(db, "R3")["closed_reason"]
    assert roll(db, "R4")["status"] == "cancelled"
    baru = [r for r in db.wh_fabric_rolls.docs if r["roll_no"].startswith("RL-UJI")]
    assert len(baru) == 1 and baru[0]["remaining_kg"] == 12.0 and baru[0]["location_id"] == "L1"
    buka = [r for r in db.wh_fabric_rolls.docs if r["material_id"] == "M1" and r["status"] in fre.OPEN_STATUSES]
    assert round(sum(fre.remaining_of(r) for r in buka), 3) == 51.5
    gerak = {(g["roll_no"], g["movement_type"], g["qty"]) for g in db.wh_fabric_roll_movements.docs}
    assert ("RL-1", "adjust", -0.5) in gerak and ("RL-3", "adjust", -10.0) in gerak
    # aman diulang: tidak ada yang berubah dua kali
    again = run(eng._sinkron_roll(db, USER, run(_sess_now(db)), ev, meta, default_home="L1", pos_zone={},
                                  loc_docs=locs))
    assert again == {} and len([r for r in db.wh_fabric_rolls.docs if r["roll_no"].startswith("RL-UJI")]) == 1


def test_approve_ujung_ke_ujung_stok_sama_dengan_isi_roll(env):  # noqa: F811 (fixture mesin opname)
    """KN1 sistem 125 kg di GD-L2 = roll A 100 + B 25. Dihitung: A ditimbang 98, B tidak ditemukan, satu roll tanpa
    label 20 → hitung 118, selisih −7 (nilai −7 × 55.000 = −385.000). Sesudah disetujui: stok 118 = A 98 + roll baru 20;
    B ditutup. KN2 (100 kg, roll C 100) dihitung sesuai catatan → tanpa selisih, roll tetap."""
    db = env.db
    seed(db)
    db.wh_fabric_rolls.docs += [
        {"id": "A", "roll_no": "RL-A", "material_id": "KN1", "uom": "kg", "weight_kg": 100.0, "remaining_kg": 100.0,
         "status": "in_stock", "location_id": "L2"},
        {"id": "B", "roll_no": "RL-B", "material_id": "KN1", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 25.0,
         "status": "in_stock", "location_id": "L2"},
        {"id": "C", "roll_no": "RL-C", "material_id": "KN2", "uom": "kg", "weight_kg": 100.0, "remaining_kg": 100.0,
         "status": "in_stock", "location_id": "L2"}]
    s = run(eng.create_session(db, USER, location_id="L2", material_codes=[], kinds=["bahan"]))
    env.clock.t = at(5)
    run(eng.record_roll_count(db, USER, run(eng.get_session(db, s["id"])), roll=roll(db, "A"), bin_id="",
                              bin_label="lantai", qty=98))
    run(eng.record_count(db, USER, run(eng.get_session(db, s["id"])), mat=next(
        m for m in db.rahaza_materials.docs if m["id"] == "KN1"), bin_id="", bin_label="lantai", qty=1, roll_qty=20))
    run(eng.record_roll_count(db, USER, run(eng.get_session(db, s["id"])), roll=roll(db, "C"), bin_id="",
                              bin_label="lantai", qty=None))
    env.clock.t = at(10)
    out = run(_flow(db, s["id"]))
    assert env.stock("KN1", "L2") == 118.0 and env.stock("KN2", "L2") == 100.0
    assert out["summary"]["roll"]["ditutup"] == 1 and out["summary"]["roll"]["baru"] == 1
    assert roll(db, "A")["remaining_kg"] == 98.0 and roll(db, "B")["status"] == "cancelled"
    buka = [r for r in db.wh_fabric_rolls.docs if r["material_id"] == "KN1" and r["status"] in fre.OPEN_STATUSES]
    assert round(sum(fre.remaining_of(r) for r in buka), 3) == 118.0
    assert roll(db, "C")["remaining_kg"] == 100.0
    assert env.je_lines() == [("1-1401", 0.0, 385000.0), ("5-1950", 385000.0, 0.0)]


def test_sinkron_roll_baris_cara_lama_tidak_mengubah_roll(db):
    s = _sess(db)
    ev = {"lines": [{"key": "M1", "material_id": "M1", "material_code": "KN-K31-GRY",
                     "entries": [{"bin_id": "", "counted_qty": 40}]}]}
    hasil = run(eng._sinkron_roll(db, USER, s, ev, {m["id"]: m for m in db.rahaza_materials.docs}, default_home="L1",
                                  pos_zone={}, loc_docs={}))
    assert hasil["tanpa_rincian_roll"] == ["KN-K31-GRY"] and roll(db, "R3")["status"] == "partly_issued"
    assert run(eng._sinkron_roll(db, USER, {**s, "roll_import_id": "imp"}, ev, {}, default_home="L1", pos_zone={},
                                 loc_docs={})) == {}


# ═════════════════════ 2. PENYESUAIAN KAIN LEWAT ROLL ═════════════════════
@pytest.fixture
def adj(db, monkeypatch):
    import routes.rahaza_inventory_stock as ris
    from core import location_resolver
    db.rahaza_material_stock.docs += [{"id": "st1", "material_id": "M1", "location_id": "L1", "qty": 55.0},
                                      {"id": "st2", "material_id": "AC", "location_id": "L2", "qty": 100.0}]
    calls = []

    async def ada(*a, **k):
        return True

    async def add(mid, loc, qty, **k):
        calls.append(("add", mid, qty))
        row = next(r for r in db.rahaza_material_stock.docs if r["material_id"] == mid and r["location_id"] == loc)
        row["qty"] += qty

    async def issue(mid, loc, qty, **k):
        calls.append(("issue", mid, qty))
        row = next(r for r in db.rahaza_material_stock.docs if r["material_id"] == mid and r["location_id"] == loc)
        row["qty"] -= qty

    async def ident(*a, **k):
        return {}

    async def post(*a, **k):
        return {"ok": True}
    monkeypatch.setattr(location_resolver, "location_exists", ada)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(stock_service, "issue", issue)
    monkeypatch.setattr(stock_service, "identity_meta", ident)
    monkeypatch.setattr(ris, "post_inventory_adjust", post)
    return ris, calls


def test_kurangi_kain_wajib_menunjuk_roll(db, adj):
    ris, calls = adj
    with pytest.raises(HTTPException) as e:
        run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=-5, reason="rusak noda"))
    assert e.value.status_code == 400 and "per roll" in e.value.detail and not calls
    with pytest.raises(HTTPException) as e:          # Σ per roll ≠ qty
        run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=-5, reason="rusak noda",
                                      roll_reductions=[{"roll_id": "R1", "qty": 3}]))
    assert "harus sama" in e.value.detail and not calls
    with pytest.raises(HTTPException) as e:          # melebihi sisa roll
        run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=-12, reason="rusak noda",
                                      roll_reductions=[{"roll_id": "R3", "qty": 12}]))
    assert "hanya bersisa 10" in e.value.detail and not calls
    mv = run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=-5, reason="rusak noda",
                                       roll_reductions=[{"roll_id": "R1", "qty": 3}, {"roll_id": "R2", "qty": 2}]))
    assert calls == [("issue", "M1", 5.0)]
    assert roll(db, "R1")["remaining_kg"] == 22.0 and roll(db, "R2")["remaining_kg"] == 18.0
    assert mv["roll_nos"] == ["RL-1", "RL-2"]


def test_tambah_kain_menerbitkan_roll_dan_aksesoris_tetap(db, adj):
    ris, calls = adj
    mv = run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=12, reason="ditemukan",
                                       rolls=[7, 5]))
    baru = [r for r in db.wh_fabric_rolls.docs if r["roll_no"].startswith("RL-UJI")]
    assert [r["remaining_kg"] for r in baru] == [7.0, 5.0] and mv["roll_nos"] == ["RL-UJI-001", "RL-UJI-002"]
    with pytest.raises(HTTPException):
        run(ris.apply_material_adjust(db, USER, material_id="M1", location_id="L1", delta=12, reason="ditemukan",
                                      rolls=[7, 4]))
    run(ris.apply_material_adjust(db, USER, material_id="AC", location_id="L2", delta=-3, reason="hilang dihitung"))
    assert calls[-1] == ("issue", "AC", 3.0)


# ═════════════════════ 3. PINDAH LOKASI KAIN ═════════════════════
def test_pindah_kain_roll_utuh(db):
    m1 = db.rahaza_materials.docs[0]
    with pytest.raises(HTTPException) as e:
        run(fre.check_move(db, m1, ["R1"], 20, from_location_id="L1"))
    assert "roll utuh" in e.value.detail
    with pytest.raises(HTTPException):
        run(fre.check_move(db, m1, [], 20, from_location_id="L1"))
    rolls = run(fre.check_move(db, m1, ["R1", "R2"], 45, from_location_id="L1"))
    run(fre.move_rolls(db, rolls, to_location_id="L2", to_location_name="Gudang Lantai 1",
                       ref={"type": "material_transfer", "id": "mv1"}, user=USER))
    r1 = roll(db, "R1")
    assert r1["location_id"] == "L2" and r1["position_id"] == "" and r1["position_barcode"] == ""
    assert {g["movement_type"] for g in db.wh_fabric_roll_movements.docs} == {"transfer"}
    with pytest.raises(HTTPException):                   # sudah tidak di lokasi asal
        run(fre.check_move(db, m1, ["R1"], 25, from_location_id="L1"))


def test_surat_jalan_internal_menolak_kain(db, monkeypatch):
    import routes.wms_delivery_notes as dn
    from core import location_resolver, stock_transfer

    async def ada(*a, **k):
        return True

    async def kosong(*a, **k):
        return set()

    async def lolos(*a, **k):
        return None

    async def label(_db, lid):
        return lid
    monkeypatch.setattr(location_resolver, "location_exists", ada)
    monkeypatch.setattr(stock_transfer, "blocked_ids", kosong)
    monkeypatch.setattr(stock_transfer, "assert_destination", lolos)
    monkeypatch.setattr(dn, "_location_label", label)
    with pytest.raises(HTTPException) as e:
        run(dn._internal_payload(db, from_location_id="L1", to_location_id="L2",
                                 lines=[{"material_id": "M1", "qty": 25}]))
    assert "Pindah lokasi" in e.value.detail
    out = run(dn._internal_payload(db, from_location_id="L1", to_location_id="L2",
                                   lines=[{"material_id": "AC", "qty": 10}]))
    assert out["lines"][0]["qty_base"] == 10


# ═════════════════════ 4. PENERIMAAN KAIN WAJIB RINCIAN ROLL ═════════════════════
def test_penerimaan_kain_wajib_rincian_gulungan_sebelum_klaim():
    import routes.warehouse as wh
    src = inspect.getsource(wh)
    i_guard = src.index("fabric_roll_engine.per_roll(mat_r)")
    i_claim = src.index("KLAIM ATOMIK SEBELUM EFEK SAMPING")
    assert i_guard < i_claim and "kain dilacak per roll" in src


# ═════════════════════ LAYAR ═════════════════════
def test_layar_memakai_pemilih_roll():
    opn = fe("WMSOpnameScanModule.jsx")
    assert "roll-undo" in opn and "opname-roll-qty" in opn and "roll_qty" in opn
    for f in ("RahazaStockModule.jsx", "InventoryScrapModule.jsx"):
        assert "PilihRollKain" in fe(f)
    assert "roll_ids" in fe("warehouse/PilihRollKain.jsx") and "roll_reductions" in fe("warehouse/PilihRollKain.jsx")
