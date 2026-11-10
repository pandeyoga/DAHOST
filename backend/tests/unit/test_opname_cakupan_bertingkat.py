"""Uji unit HERMETIK cakupan opname BERTINGKAT (10 Nov 2026).

Permintaan owner: "ketika buat opname harus jelas mau pilih all gudang, atau hanya zona atau rak. ingat ada level
levelnya … bisa pilih beberapa rak". Mesin (`core.opname_engine`) kini menerima:
  * `with_areas=True`       → seluruh gudang beserta zona anaknya (lokasi ber-`parent_id`), karantina tidak ikut;
  * `sub_type='area'`       → beberapa zona anak sekaligus (level LOKASI: stok + penempatan);
  * `sub_type='zone'|'rack'|'bin'` + `sub_ids` → beberapa zona/rak/bin `wh_*` (level RAK: penempatan saja);
  * `sub_id` tunggal pemanggil lama tetap jalan.

Data uji (dihitung tangan):
  GD-L1 Gudang Lantai 1 (bahan) ── GD-L1-ACC Ruang Aksesoris · GD-L1-RAK Area Rak Stok · GD-L1-QC Area QC (karantina)
                                   (+ satu kantor anak yang tidak boleh ikut)
  zona wh_*: ZN-FG → RAK (rak A1, A2) · ZN-ACC → ACC (rak B3, lewat peta migrasi) · ZN-QC → QC (rak Q1) ·
             ZN-UT → langsung GD-L1 (rak M1)
  stok: KN1 100 @GD-L1 · FG1 8 @RAK · FG1 4 @QC · FG2 3 @RAK · AC1 50 @ACC
  Hitung zona ACC + RAK: AC1 47 (−3 × 2.000), AC2 7 baru di bin B3 (→ ACC), FG1 6 (−2 × 50.000), FG2 3,
  FGN 2 baru di lantai (barang jadi → zona berperan fg = RAK). KN1 @GD-L1 dan FG1 @QC tidak tersentuh.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_opname_cakupan_bertingkat.py -q
"""
import asyncio
import os
import pathlib
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from core import opname_engine as eng  # noqa: E402
from core import stock_service  # noqa: E402
import test_k9_opname_engine as k9  # noqa: E402

# fixture `env` (Mongo palsu + stok + posting palsu) dipakai ulang dari uji mesin opname K9
env = k9.env
USER, _count, _flow = k9.USER, k9._count, k9._flow
LAYAR = pathlib.Path(BACKEND).parent / "frontend" / "src" / "components" / "erp" / "WMSOpnameScanModule.jsx"


def run(coro):
    return asyncio.run(coro)


def seed(db):
    db.rahaza_locations.docs += [
        {"id": "G1", "code": "GD-L1", "name": "Gudang Lantai 1", "type": "gedung", "storage_role": "bahan",
         "active": True},
        {"id": "ACC", "code": "GD-L1-ACC", "name": "Ruang Aksesoris", "type": "zona", "parent_id": "G1",
         "storage_role": "aksesoris", "active": True},
        {"id": "RAK", "code": "GD-L1-RAK", "name": "Area Rak Stok", "type": "zona", "parent_id": "G1",
         "storage_role": "fg", "active": True},
        {"id": "QC", "code": "GD-L1-QC", "name": "Area QC", "type": "zona", "parent_id": "G1",
         "storage_role": "karantina", "active": True},
        {"id": "KADM", "code": "GD-L1-ADM", "name": "Meja Admin", "type": "kantor", "parent_id": "G1", "active": True},
        {"id": "KTR", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True},
        {"id": "G2", "code": "GD-L2", "name": "Gudang Lantai 2", "type": "gedung", "storage_role": "bahan",
         "active": True}]
    db.wh_zones.docs += [
        {"id": "ZFG", "code": "ZN-FG", "name": "Zona Barang Jadi", "location_id": "RAK"},
        {"id": "ZACC", "code": "ZN-ACC", "name": "Zona Aksesoris"},
        {"id": "ZQC", "code": "ZN-QC", "name": "Zona QC", "location_id": "QC"},
        {"id": "ZM", "code": "ZN-UT", "name": "Zona Utama", "location_id": "G1"}]
    db.wh_location_migration_map.docs.append({"rahaza_location_id": "ACC", "wh_zone_id": "ZACC", "active": True})
    db.wh_racks.docs += [
        {"id": "RA1", "zone_id": "ZFG", "code": "A1", "name": "Rak A1"},
        {"id": "RA2", "zone_id": "ZFG", "code": "A2", "name": "Rak A2"},
        {"id": "RB3", "zone_id": "ZACC", "code": "B3", "name": "Rak B3"},
        {"id": "RQ", "zone_id": "ZQC", "code": "Q1", "name": "Rak QC"},
        {"id": "RM", "zone_id": "ZM", "code": "M1", "name": "Rak M1"}]

    def pos(pid, rack, zone, barcode, mid=None, qty=0):
        return {"id": pid, "rack_id": rack, "zone_id": zone, "barcode": barcode, "label": barcode,
                "material_id": mid, "qty": qty}
    db.wh_positions.docs += [pos("PA1", "RA1", "ZFG", "A1-1", "FG1", 5), pos("PA1b", "RA1", "ZFG", "A1-2"),
                             pos("PA2", "RA2", "ZFG", "A2-1", "FG2", 3), pos("PB3", "RB3", "ZACC", "B3-1", "AC1", 10),
                             pos("PQ", "RQ", "ZQC", "Q1-1", "FG1", 4), pos("PM", "RM", "ZM", "M1-1", "KN1", 20)]
    db.rahaza_materials.docs += [
        {"id": "KN1", "code": "KN-CND-01", "name": "Kain Candy", "type": "fabric", "unit": "kg", "unit_cost": 55000.0},
        {"id": "FG1", "code": "DA-FG-1", "name": "Gamis", "type": "fg", "unit": "pcs", "unit_cost": 50000.0},
        {"id": "FG2", "code": "DA-FG-2", "name": "Tunik", "type": "fg", "unit": "pcs", "unit_cost": 40000.0},
        {"id": "FGN", "code": "DA-FG-9", "name": "Khimar", "type": "fg", "unit": "pcs", "unit_cost": 20000.0},
        {"id": "AC1", "code": "A-BIS-01", "name": "Kancing", "type": "accessory", "unit": "pcs", "unit_cost": 2000.0},
        {"id": "AC2", "code": "A-RES-01", "name": "Resleting", "type": "accessory", "unit": "pcs", "unit_cost": 1000.0}]
    db[stock_service.STOCK].docs += [
        {"id": "s1", "material_id": "KN1", "location_id": "G1", "qty": 100.0},
        {"id": "s2", "material_id": "FG1", "location_id": "RAK", "qty": 8.0},
        {"id": "s3", "material_id": "FG1", "location_id": "QC", "qty": 4.0},          # karantina
        {"id": "s4", "material_id": "FG2", "location_id": "RAK", "qty": 3.0},
        {"id": "s5", "material_id": "AC1", "location_id": "ACC", "qty": 50.0}]


def _keys(sess):
    return sorted(ln["key"] for ln in sess["lines"])


# ═══════════════════════════ 1. fungsi murni ═══════════════════════════
def test_label_cakupan_dan_pohon_lokasi_fungsi_murni():
    assert eng.join_names(list("ABCDEFGH")) == "A, B, C, D, E, F (+2 lainnya)"
    assert eng.join_names(["A1", "A2", "B3"]) == "A1, A2, B3"
    racks = [{"id": "1", "code": "A1", "zone_id": "z1"}, {"id": "2", "code": "A1", "zone_id": "z2"},
             {"id": "3", "code": "B3", "zone_id": "z1"}]
    zones = {"z1": {"code": "ZN-FG"}, "z2": {"code": "ZN-ACC"}}
    assert eng.sub_label("rack", racks, zones_by_id=zones) == "Rak ZN-FG/A1, ZN-ACC/A1, B3"   # kode kembar → awalan
    g1 = {"id": "G1", "name": "Gudang Lantai 1"}
    assert eng.sub_label("area", [g1, {"id": "ACC", "name": "Ruang Aksesoris"}], home=g1) == \
        "di luar zona + Zona Ruang Aksesoris"
    assert eng.sub_label("bin", [{"id": "p", "barcode": "A1-1"}]) == "Bin A1-1"
    # induk berputar tidak membuat macet
    loop = [{"id": "a", "parent_id": "b"}, {"id": "b", "parent_id": "a"}]
    assert [x["id"] for x in eng.descendants(loop, "a")] == ["b"]
    assert eng.top_of({x["id"]: x for x in loop}, "a") in ("a", "b")
    # rumah barang baru: bin → zona tautannya; selain itu peran lokasi = jenis barang; selain itu rumah sesi
    docs = {"ACC": {"id": "ACC", "storage_role": "aksesoris"}, "RAK": {"id": "RAK", "storage_role": "fg"}}
    kw = dict(default="ACC", zone_home={"ZFG": "RAK"}, pos_zone={"PA1": "ZFG"}, loc_ids=["ACC", "RAK", "ZFG"],
              loc_docs=docs)
    assert eng.home_location_for({"kind": "aksesoris", "entries": [{"bin_id": "PA1"}]}, **kw) == "RAK"
    assert eng.home_location_for({"kind": "fg", "entries": [{"bin_id": ""}]}, **kw) == "RAK"
    assert eng.home_location_for({"kind": "bahan", "entries": []}, **kw) == "ACC"


# ═══════════════════════════ 2. pilihan lokasi bertingkat ═══════════════════════════
def test_daftar_lokasi_bertingkat_tanpa_kantor(env):
    db = env.db
    seed(db)
    rows = {r["code"]: r for r in run(eng.list_locations(db))}
    assert "KTR-PST" not in rows and "GD-L1-ADM" not in rows                      # kantor tidak muncul sama sekali
    g1 = rows["GD-L1"]
    assert g1["top"] is True and rows["GD-L2"]["top"] is True
    assert [(a["code"], a["quarantine"]) for a in g1["areas"]] == \
        [("GD-L1-ACC", False), ("GD-L1-QC", True), ("GD-L1-RAK", False)]
    assert {z["id"]: z["area_id"] for z in g1["zones"]} == {"ZACC": "ACC", "ZFG": "RAK", "ZM": "G1"}   # ZN-QC tidak
    assert sorted(r["id"] for r in g1["racks"]) == ["RA1", "RA2", "RB3", "RM"]
    assert "PQ" not in {b["id"] for b in g1["bins"]}
    acc = rows["GD-L1-ACC"]
    assert acc["top"] is False and acc["top_id"] == "G1" and [z["id"] for z in acc["zones"]] == ["ZACC"]
    assert rows["GD-L2"]["areas"] == [] and rows["GD-L2"]["zones"] == []


def test_seluruh_gudang_ikut_zona_anak_tanpa_karantina(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", with_areas=True))
    assert s["level"] == "lokasi" and s["sub_scope"] is None
    assert s["location_ids"] == ["G1", "ACC", "RAK", "ZACC", "ZFG", "ZM"]               # QC & ZN-QC tidak ikut
    assert {ln["material_id"]: ln["snapshot_qty"] for ln in s["lines"]} == \
        {"AC1": 50.0, "FG1": 8.0, "FG2": 3.0, "KN1": 100.0}                              # FG1 karantina (4) tidak
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · seluruh gudang"
    assert s["home_location_id"] == "G1" and s["floor_code"] == "GD-L1"
    # pemanggil lama (tanpa with_areas) = lokasi itu saja, persis seperti dulu
    assert run(eng.location_scope(db, "G1"))["location_ids"] == ["G1", "ZM"]


# ═══════════════════════════ 3. beberapa rak / zona sekaligus ═══════════════════════════
def test_banyak_rak_baris_dari_semua_posisi_rak_terpilih(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", sub_type="rack", sub_ids=["RA1", "RB3"], with_areas=True))
    assert s["level"] == "rak" and _keys(s) == ["AC1@PB3", "FG1@PA1"]                  # rak A2 (FG2) tidak dipilih
    assert s["sub_scope"] == {"type": "rack", "id": "RA1", "ids": ["RA1", "RB3"], "label": "Rak A1, B3"}
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · Rak A1, B3"
    sess = run(eng.get_session(db, s["id"], for_write=True))
    with pytest.raises(HTTPException) as e:                                             # bin rak lain ditolak
        run(eng.resolve_count_bin(db, sess, bin_id="PA2"))
    assert e.value.status_code == 400 and "di luar cakupan" in e.value.detail
    assert run(eng.resolve_count_bin(db, sess, bin_id="PB3"))[0] == "PB3"
    env.clock.t = k9.at(5)
    run(_count(db, s["id"], "FG1", 5, bin_id="PA1"))
    run(_count(db, s["id"], "AC1", 9, bin_id="PB3"))
    out = run(_flow(db, s["id"]))
    assert out["status"] == "approved" and env.jes == []                                # penempatan saja
    assert env.stock("AC1", "ACC") == 50.0 and env.stock("FG1", "RAK") == 8.0
    pos = {p["id"]: (p["material_id"], p["qty"]) for p in db.wh_positions.docs}
    assert pos["PB3"] == ("AC1", 9.0) and pos["PA1"] == ("FG1", 5.0) and pos["PA2"] == ("FG2", 3)


def test_banyak_zona_rak_dan_bin(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", sub_type="zone", sub_ids=["ZFG", "ZACC"], with_areas=True))
    assert s["level"] == "rak" and _keys(s) == ["AC1@PB3", "FG1@PA1", "FG2@PA2"]
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · Zona ZN-FG, ZN-ACC"
    b = run(eng.create_session(db, USER, location_id="G1", sub_type="bin", sub_ids=["PA2", "PM"], with_areas=True))
    assert _keys(b) == ["FG2@PA2", "KN1@PM"] and b["scope_label"].endswith("· Bin A2-1, M1-1")


def test_banyak_zona_anak_hitung_stok_dan_barang_baru_ke_zona_yang_benar(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", sub_type="area", sub_ids=["RAK", "ACC"]))
    assert s["level"] == "lokasi" and s["sub_scope"]["ids"] == ["ACC", "RAK"]         # urut kode
    assert s["location_ids"] == ["ACC", "RAK", "ZACC", "ZFG"]
    assert {ln["material_id"]: ln["snapshot_qty"] for ln in s["lines"]} == {"AC1": 50.0, "FG1": 8.0, "FG2": 3.0}
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · Zona Ruang Aksesoris, Area Rak Stok"
    assert s["home_location_id"] == "ACC" and s["floor_code"] == "GD-L1"
    env.clock.t = k9.at(5)
    run(_count(db, s["id"], "AC1", 47))
    run(_count(db, s["id"], "AC2", 7, bin_id="PB3"))       # baru, di bin zona ACC
    run(_count(db, s["id"], "FG1", 6, bin_id="PA1"))
    run(_count(db, s["id"], "FG2", 3, bin_id="PA2"))
    run(_count(db, s["id"], "FGN", 2))                     # baru, di lantai → zona berperan barang jadi
    env.clock.t = k9.at(9)
    assert run(_flow(db, s["id"]))["status"] == "approved"
    assert (env.stock("AC1", "ACC"), env.stock("AC2", "ACC"), env.stock("FG1", "RAK"), env.stock("FGN", "RAK")) == \
        (47.0, 7.0, 6.0, 2.0)
    assert env.stock("FG1", "QC") == 4.0 and env.stock("KN1", "G1") == 100.0          # di luar cakupan: utuh
    assert env.stock("FGN", "ACC") == 0 and env.stock("AC2", "RAK") == 0
    mv = {m["material_id"]: m["to_location_id"] for m in db.rahaza_material_movements.docs}
    assert mv["AC2"] == "ACC" and mv["FGN"] == "RAK" and mv["FG1"] == "RAK"
    new_row = next(r for r in db[stock_service.STOCK].docs if r["material_id"] == "FGN")
    assert new_row["location_code"] == "GD-L1-RAK"
    # 6.000 kurang aksesoris, 7.000 lebih aksesoris, 100.000 kurang FG1, 40.000 lebih FGN — satu jurnal sesi
    assert len(env.jes) == 1 and env.je_lines() == sorted([
        ("1-1402", 7000.0, 0), ("5-1950", 0, 7000.0), ("5-1950", 6000.0, 0), ("1-1402", 0, 6000.0),
        ("1-1404", 40000.0, 0), ("5-1950", 0, 40000.0), ("5-1950", 100000.0, 0), ("1-1404", 0, 100000.0)])


def test_gudang_di_luar_zona_saja(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", sub_type="area", sub_ids=["G1"]))
    assert s["location_ids"] == ["G1", "ZM"] and [ln["material_id"] for ln in s["lines"]] == ["KN1"]
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · di luar zona"


# ═══════════════════════════ 4. kompatibilitas & aturan lama ═══════════════════════════
def test_sub_id_tunggal_dan_lokasi_zona_langsung_tetap_jalan(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="G1", sub_type="rack", sub_id="RA1", with_areas=True))
    assert s["sub_scope"] == {"type": "rack", "id": "RA1", "ids": ["RA1"], "label": "Rak A1"}
    assert _keys(s) == ["FG1@PA1"]
    # pemanggil lama (Portal Aksesoris, impor roll): lokasi = zona itu sendiri, tanpa sub-cakupan
    a = run(eng.create_session(db, USER, location_id="ACC", kinds=["aksesoris"], source="aksesoris"))
    assert a["location_ids"] == ["ACC", "ZACC"] and a["scope_label"] == "GD-L1-ACC — Ruang Aksesoris · Aksesoris"
    assert a["home_location_id"] == "ACC" and a["floor_code"] == "GD-L1-ACC"
    # sesi lama tanpa field baru (dibuat sebelum 10 Nov) tetap bisa dihitung & disetujui
    doc = next(d for d in db[eng.SESS].docs if d["id"] == a["id"])
    for k in ("home_location_id", "zone_home", "floor_code", "area_ids", "with_areas"):
        doc.pop(k)
    env.clock.t = k9.at(5)
    run(_count(db, a["id"], "AC1", 49))
    run(_flow(db, a["id"]))
    assert env.stock("AC1", "ACC") == 49.0


def test_stok_awal_hanya_seluruh_gudang_atau_zona(env):
    db = env.db
    seed(db)
    for st, ids in (("rack", ["RA1", "RA2"]), ("zone", ["ZFG"]), ("bin", ["PA1"])):
        with pytest.raises(HTTPException) as e:
            run(eng.create_session(db, USER, location_id="G1", sub_type=st, sub_ids=ids, opening=True, with_areas=True))
        assert e.value.status_code == 400 and "stok awal" in e.value.detail
    z = run(eng.create_session(db, USER, location_id="G1", sub_type="area", sub_ids=["ACC"], opening=True))
    assert z["mode"] == eng.MODE_OPENING and z["scope_label"] == "Stok awal · GD-L1 — Gudang Lantai 1 · Zona Ruang Aksesoris"
    g = run(eng.create_session(db, USER, location_id="G1", opening=True, with_areas=True))
    assert g["mode"] == eng.MODE_OPENING and g["level"] == "lokasi"


def test_cakupan_salah_ditolak(env):
    db = env.db
    seed(db)
    cases = [
        (dict(sub_type="area", sub_ids=["QC"]), "KARANTINA"),
        (dict(sub_type="area", sub_ids=["G2"]), "bukan bagian gudang"),
        (dict(sub_type="rack", sub_ids=["RQ"], with_areas=True), "tidak tertaut"),       # rak zona karantina
        (dict(sub_type="rack", sub_ids=[]), "Pilih minimal satu rak"),
        (dict(sub_ids=["RA1"]), "wajib diisi"),
        (dict(sub_type="shelf", sub_ids=["RA1"]), "Cakupan harus"),
    ]
    for kw, msg in cases:
        with pytest.raises(HTTPException) as e:
            run(eng.create_session(db, USER, location_id="G1", **kw))
        assert e.value.status_code == 400 and msg in e.value.detail, (kw, e.value.detail)
    with pytest.raises(HTTPException) as e:
        run(eng.create_session(db, USER, location_id="QC"))
    assert "KARANTINA" in e.value.detail


def test_rute_menerima_banyak_id(env, monkeypatch):
    from routes import wms_opname3 as op
    db = env.db
    seed(db)

    async def auth(_req):
        return USER

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(op, "require_auth", auth)
    monkeypatch.setattr(op, "get_db", lambda: db)
    monkeypatch.setattr(op, "log_activity", noop)
    out = run(op.create_session(op.SessionCreateIn(location_id="G1", sub_scope_type="rack",
                                                   sub_scope_ids=["RA1", "RA2"], with_areas=True), types.SimpleNamespace()))
    assert out["level"] == "rak" and out["lines"] == 2 and out["scope_label"] == "GD-L1 — Gudang Lantai 1 · Rak A1, A2"
    old = run(op.create_session(op.SessionCreateIn(location_id="G1", sub_scope_type="rack", sub_scope_id="RM"),
                                types.SimpleNamespace()))
    assert old["lines"] == 1                                                   # bentuk masukan lama (satu id)
    locs = run(op.list_locations(types.SimpleNamespace()))
    assert [x["code"] for x in locs if x["top"]] == ["GD-L1", "GD-L2"]


# ═══════════════════════════ 5. layar ═══════════════════════════
def test_layar_mengikuti_tingkatan_dan_centang_banyak():
    if not LAYAR.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    s = LAYAR.read_text(encoding="utf-8")
    # langkah 1: gudang (tingkat teratas saja, kantor tidak), langkah 2: cakupan, lalu daftar centang
    assert "l.top !== false" in s and "l.type !== 'kantor'" in s
    assert s.index('data-testid="opname-location"') < s.index('data-testid="opname-cakupan"') \
        < s.index("<DaftarCentang")
    for teks in ("'Seluruh gudang'", "'Zona tertentu'", "'Rak tertentu'", "'Bin tertentu'"):
        assert teks in s
    # banyak pilihan: centang, kelompok per induk, pilih semua per kelompok, cari
    assert "<Checkbox" in s and "Pilih semua" in s and "Cari kode atau nama" in s
    assert "loc.racks.filter((r) => r.zone_id === z.id)" in s and "loc.bins.filter((b) => b.rack_id === r.id)" in s
    # masukan baru ke mesin; pilihan "Level" satu zona/rak/bin yang lama sudah tidak ada
    assert "sub_scope_ids" in s and "with_areas: true" in s
    assert "opname-sub-type" not in s and "Per rak (penempatan saja)" not in s and "sub_scope_id:" not in s


# ══ 10 Nov 2026 (keputusan owner): "Seluruh gudang" tanpa area produksi ══
def test_area_produksi_dikenali():
    from core import opname_engine as oe
    assert oe._is_production_area({"type": "produksi", "code": "GD-L2-CUT"})
    assert oe._is_production_area({"type": "gudang", "storage_role": "cutting"})
    assert not oe._is_production_area({"type": "gudang", "storage_role": "bahan"})
    src = (pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"
           / "WMSOpnameScanModule.jsx").read_text(encoding="utf-8")
    assert "Area produksi (" in src and "a.production" in src


def test_seluruh_gudang_tanpa_area_produksi_tetapi_bisa_dipilih_zona(env):
    db = env.db
    seed(db)
    db.rahaza_locations.docs.append({"id": "CUT", "code": "GD-L1-CUT", "name": "Area Cutting", "type": "produksi",
                                     "parent_id": "G1", "storage_role": "cutting", "active": True})
    s = run(eng.create_session(db, USER, location_id="G1", with_areas=True))
    assert "CUT" not in s["location_ids"]
    assert s["scope_label"] == "GD-L1 — Gudang Lantai 1 · seluruh gudang (tanpa area produksi: GD-L1-CUT)"
    s2 = run(eng.create_session(db, USER, location_id="G1", sub_type="area", sub_ids=["CUT"]))
    assert "CUT" in s2["location_ids"]
