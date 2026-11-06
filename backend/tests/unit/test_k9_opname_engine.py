"""Uji unit HERMETIK paket 3b-1 (2026-11-02) — mesin opname tunggal K9 (`core.opname_engine`).

Angka harapan DIHITUNG TANGAN:
  * Kain 125 kg belum dirak, dihitung 125 di bin lokasi → selisih 125 − 125 = 0, stok tetap 125,
    bin = 125 (mesin lama: stok sistem = isi bin 0 → +125 → stok 250).
  * FG minus −3, dihitung 5 → selisih 5 − (−3) = +8; nilai 8 × WAC 50.000 = 400.000
    → Dr 1-1404 400.000 / Cr 5-1950 400.000; stok = 5.
  * Tanpa kunci: snapshot 100; keluar 20 SEBELUM dihitung; dihitung 78; keluar 5 SESUDAH dihitung.
      stok sistem saat dihitung = 100 − 20 = 80 → selisih 78 − 80 = −2 (nilai −2 × 10.000 = −20.000)
      stok akhir = stok kini 75 + (−2) = 73 (= fisik 78 − 5 yang keluar sesudah dihitung).
  * Aksesoris: 50 → 47 (−3 × 2.000 = −6.000) → Dr 5-1950 / Cr 1-1402 6.000;
      rusak 10 → 8 (−2 × 1.000 = −2.000) → Dr 6-4300 / Cr 1-1402 2.000.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_k9_opname_engine.py -q
"""
import asyncio
import copy
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import coa_bindings as cb  # noqa: E402
from core import opname_engine as eng  # noqa: E402
from core import stock_service  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

USER = {"id": "u-spv", "name": "SPV Uji", "email": "spv@x", "role": "superadmin"}
T0 = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)          # 08:00 WIB


def run(coro):
    return asyncio.run(coro)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


# ── Mongo palsu + array_filters / upsert / find_one_and_update (secukupnya untuk mesin) ──
class Coll(fm.FakeCollection):
    async def update_one(self, q, upd, upsert=False, array_filters=None):
        if array_filters:
            flt = {k[2:]: v for k, v in array_filters[0].items()}
            n = 0
            for d in self.docs:
                if not fm.match(d, q):
                    continue
                for path, val in (upd.get("$set") or {}).items():
                    arr, field = path.split(".$[l].")
                    for el in d.get(arr) or []:
                        if fm.match(el, flt):
                            el[field] = copy.deepcopy(val)
                n += 1
            return fm._Result(matched=n, modified=n)
        res = await super().update_one(q, upd)
        if res.matched_count or not upsert:
            return res
        doc = {k: v for k, v in q.items() if not k.startswith("$") and not isinstance(v, dict)}
        doc.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
        doc.update(copy.deepcopy(upd.get("$set") or {}))
        self.docs.append(doc)
        return fm._Result(matched=0, modified=0)

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if fm.match(d, q):
                before = copy.deepcopy(d)
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = copy.deepcopy(v)
                return before
        return None


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Coll(name)
        return self._cols[name]


@pytest.fixture
def env(monkeypatch):
    """Jam terkendali, stock_service.adjust palsu (pipeline update tidak didukung Mongo palsu),
    penomoran palsu, dan mesin posting palsu memakai profil BAWAAN."""
    clock = types.SimpleNamespace(t=T0)
    monkeypatch.setattr(eng, "_now", lambda: clock.t)
    db = DB()

    async def adjust(material_id, location_id, counted_qty, *, meta=None, ref=None, actor=None, db=None,
                     input_uom=None):
        coll = db[stock_service.STOCK]
        row = next((r for r in coll.docs if r["material_id"] == material_id and r["location_id"] == location_id), None)
        before = float((row or {}).get("qty") or 0)
        if row is None:
            row = {"id": f"st-{len(coll.docs)}", "material_id": material_id, "location_id": location_id,
                   **{k: v for k, v in (meta or {}).items() if v is not None}}
            coll.docs.append(row)
        row["qty"] = counted_qty
        db[stock_service.LEDGER].docs.append({"op": "adjust", "material_id": material_id, "location_id": location_id,
                                              "delta": round(counted_qty - before, 4), "ref": ref or {},
                                              "created_at": clock.t})
        return row
    monkeypatch.setattr(stock_service, "adjust", adjust)

    async def adjust_by(material_id, location_id, delta, *, meta=None, ref=None, actor=None, db=None):
        """2026-11-06 (Tahap 1): approve opname menulis SELISIH atomik (qty += delta)."""
        coll = db[stock_service.STOCK]
        row = next((r for r in coll.docs if r["material_id"] == material_id and r["location_id"] == location_id), None)
        if row is None:
            row = {"id": f"st-{len(coll.docs)}", "material_id": material_id, "location_id": location_id, "qty": 0.0,
                   **{k: v for k, v in (meta or {}).items() if v is not None}}
            coll.docs.append(row)
        row["qty"] = round(float(row.get("qty") or 0) + delta, 4)
        db[stock_service.LEDGER].docs.append({"op": "adjust", "material_id": material_id, "location_id": location_id,
                                              "delta": round(delta, 4), "ref": ref or {}, "created_at": clock.t})
        return row
    monkeypatch.setattr(stock_service, "adjust_by", adjust_by)

    async def gen(db_, coll, field, prefix, width, **kw):
        return f"{prefix}{len(db_[coll].docs) + 1:0{width}d}"
    import utils.counters as uc
    monkeypatch.setattr(uc, "gen_prefixed_number", gen)

    jes = []
    defaults = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}

    async def mapping(db_, key):
        return dict(defaults.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db_, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(x["debit"] for x in lines), 2) == round(sum(x["credit"] for x in lines), 2), lines
        jes.append({"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "date": d, "source_module": mod,
                    "source_ref": ref, "lines": lines})
        return {"ok": True, "je_id": jes[-1]["id"], "je_number": jes[-1]["je_number"]}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def stock(mid, loc):
        return sum(float(r.get("qty") or 0) for r in db[stock_service.STOCK].docs
                   if r["material_id"] == mid and r["location_id"] == loc)

    def issue(mid, loc, qty, when):
        """Transaksi keluar (lewat ledger, seperti stock_service.issue)."""
        row = next(r for r in db[stock_service.STOCK].docs if r["material_id"] == mid and r["location_id"] == loc)
        row["qty"] = round(row["qty"] - qty, 4)
        db[stock_service.LEDGER].docs.append({"op": "issue", "material_id": mid, "location_id": loc,
                                              "delta": -qty, "ref": {"type": "uji"}, "created_at": when})

    def je_lines(i=-1):
        return sorted((x["account_code"], round(x["debit"], 2), round(x["credit"], 2)) for x in jes[i]["lines"])
    return types.SimpleNamespace(db=db, clock=clock, jes=jes, stock=stock, issue=issue, je_lines=je_lines)


def seed(db):
    db.rahaza_locations.docs += [
        {"id": "L2", "code": "GD-L2", "name": "Gudang Lantai 2", "storage_role": "bahan", "active": True},
        {"id": "LACC", "code": "GD-L1-ACC", "name": "Ruang Aksesoris", "storage_role": "aksesoris", "active": True},
        {"id": "LRAK", "code": "GD-L1-RAK", "name": "Area Rak Stok", "storage_role": "fg", "active": True},
        {"id": "LQC", "code": "GD-L1-QC", "name": "Area QC", "storage_role": "karantina", "active": True}]
    db.wh_location_migration_map.docs.append({"rahaza_location_id": "L2", "wh_zone_id": "Z1", "active": True})
    db.wh_zones.docs.append({"id": "Z1", "code": "ZN-L2", "name": "Zona L2"})
    db.wh_racks.docs.append({"id": "R1", "zone_id": "Z1", "code": "RK-01", "name": "Rak 1"})
    db.wh_positions.docs += [
        {"id": "P1", "zone_id": "Z1", "rack_id": "R1", "barcode": "L2-RK01-P1", "label": "S1-P1", "qty": 0,
         "material_id": None},
        {"id": "P2", "zone_id": "Z1", "rack_id": "R1", "barcode": "L2-RK01-P2", "label": "S1-P2", "qty": 30,
         "material_id": "KN2"}]
    db.rahaza_materials.docs += [
        {"id": "KN1", "code": "KN-CND-01", "name": "Kain Candy", "type": "fabric", "unit": "kg", "unit_cost": 55000.0},
        {"id": "KN2", "code": "KN-CND-02", "name": "Kain Candy 2", "type": "fabric", "unit": "kg", "unit_cost": 10000.0},
        {"id": "FG1", "code": "DA-FG-1", "name": "Gamis", "type": "fg", "unit": "pcs", "unit_cost": 50000.0,
         "wac_components": {"material": 40000.0, "labor": 10000.0, "overhead": 0.0}},
        {"id": "AC1", "code": "A-BIS-01", "name": "Kancing", "type": "accessory", "unit": "pcs", "unit_cost": 2000.0},
        {"id": "AC2", "code": "A-RES-01", "name": "Resleting", "type": "accessory", "unit": "pcs", "unit_cost": 1000.0}]
    db[stock_service.STOCK].docs += [
        {"id": "s1", "material_id": "KN1", "location_id": "L2", "qty": 125.0},
        {"id": "s2", "material_id": "KN2", "location_id": "L2", "qty": 100.0},
        {"id": "s3", "material_id": "FG1", "location_id": "LRAK", "qty": -3.0, "ownership": "cv_da",
         "inventory_category": "fg_internal"},
        {"id": "s4", "material_id": "FG1", "location_id": "LQC", "qty": 4.0},          # karantina
        {"id": "s5", "material_id": "AC1", "location_id": "LACC", "qty": 50.0},
        {"id": "s6", "material_id": "AC2", "location_id": "LACC", "qty": 10.0}]


async def _count(db, sess_id, mid, qty, bin_id="", mode="set"):
    sess = await eng.get_session(db, sess_id, for_write=True)
    mat = await eng.resolve_item(db, material_id=mid)
    return await eng.record_count(db, USER, sess, mat=mat, bin_id=bin_id, bin_label=bin_id, qty=qty, mode=mode)


async def _flow(db, sess_id, confirm_zero=False):
    s = await eng.submit(db, USER, await eng.get_session(db, sess_id), confirm_zero=confirm_zero)
    return await eng.approve(db, USER, s)


# ═══════════════════════════ 1. fungsi murni ═══════════════════════════
def test_system_qty_tanpa_kunci_snapshot_plus_ledger_sampai_counted_at():
    rows = [{"op": "issue", "delta": -20, "created_at": at(10)},
            {"op": "reserve", "delta": 5, "created_at": at(11)},            # reservasi: bukan qty fisik
            {"op": "issue", "delta": -5, "created_at": at(40)},             # sesudah dihitung
            {"op": "add", "delta": 7, "created_at": at(-5)}]                # sebelum snapshot (sudah di snapshot)
    assert eng.system_qty_at(100, rows, at(0), at(30)) == (80.0, -20.0)
    # scan susulan dicatat SESUDAH dihitung tetapi kejadiannya sebelum (ref.effective_at) → ikut
    late = {"op": "issue", "delta": -3, "created_at": at(50), "ref": {"effective_at": at(20).isoformat()}}
    assert eng.system_qty_at(100, rows + [late], at(0), at(30)) == (77.0, -23.0)
    # datetime naif dari Motor = UTC
    naive = [{"op": "issue", "delta": -20, "created_at": at(10).replace(tzinfo=None)}]
    assert eng.system_qty_at(100, naive, at(0), at(30))[0] == 80.0


def test_plan_stock_writes_set_absolut_dan_minus_hilang():
    assert eng.plan_stock_writes([{"location_id": "L", "qty": -3}], 5, "L") == [("L", 5.0)]
    assert eng.plan_stock_writes([], 4, "L") == [("L", 4.0)]
    # baris lokasi sesi menyerap; baris zona tertaut tetap
    assert eng.plan_stock_writes([{"location_id": "L", "qty": 10}, {"location_id": "Z", "qty": 5}], 12, "L") == [("L", 7.0)]
    # baris utama akan minus → baris lain di-nol-kan
    assert sorted(eng.plan_stock_writes([{"location_id": "L", "qty": 1}, {"location_id": "Z", "qty": 9}], 4, "L")) == \
        [("L", 4.0), ("Z", 0.0)]


def test_plan_penempatan_lokasi_tanpa_dobel_dan_bin_tak_discan_dibatasi():
    pos = [{"id": "P1", "material_id": None, "qty": 0}, {"id": "P2", "material_id": "B", "qty": 30},
           {"id": "P3", "material_id": "C", "qty": 9}]
    ent = [{"material_id": "A", "bin_id": "P1", "counted_qty": 125}, {"material_id": "B", "bin_id": "", "counted_qty": 20}]
    ch, over = eng.plan_location_placement(pos, ent, {"A": 125, "B": 20})
    assert ch == {"P1": ("A", 125.0), "P2": ("B", 20.0)}         # P2 tak di-scan: 30 → dibatasi hasil hitung 20
    assert over == [] and "P3" not in ch                           # C tidak dihitung di sesi ini → tak disentuh
    # dua barang di satu bin → yang terbanyak menempati, sisanya = belum dirak (overflow)
    ch, over = eng.plan_location_placement(pos, ent + [{"material_id": "B", "bin_id": "P1", "counted_qty": 5}],
                                           {"A": 125, "B": 25})
    assert ch["P1"] == ("A", 125.0) and over == [{"bin_id": "P1", "material_id": "B", "qty": 5.0}]
    # bin ter-scan 78, saldo akhir 73 (keluar 5 sesudah dihitung) → bin dibatasi 73
    ch, _ = eng.plan_location_placement(pos[:1], [{"material_id": "A", "bin_id": "P1", "counted_qty": 78}], {"A": 73})
    assert ch == {"P1": ("A", 73.0)}


def test_plan_penempatan_rak_pindah_vs_lebih():
    lines = [{"material_id": "A", "bin_id": "P1", "counted_qty": 40, "in_snapshot": False, "resolution": "pindah"},
             {"material_id": "B", "bin_id": "P2", "counted_qty": 25, "in_snapshot": True}]
    pos = [{"id": "P1", "material_id": None, "qty": 0}, {"id": "P2", "material_id": "B", "qty": 30}]
    ch, err, fnd = eng.plan_rack_placement(lines, pos, {"A": 100, "B": 30})
    assert ch == {"P1": ("A", 40.0), "P2": ("B", 25.0)} and err == [] and fnd == []
    # stok lokasi A cuma 10 → "pindah" 40 ditolak; "lebih" tidak ditempatkan (temuan saja)
    _, err, _ = eng.plan_rack_placement(lines, pos, {"A": 10, "B": 30})
    assert err == [{"material_id": "A", "penempatan": 40.0, "stok_lokasi": 10.0}]
    lines[0]["resolution"] = "lebih"
    ch, err, fnd = eng.plan_rack_placement(lines, pos, {"A": 10, "B": 30})
    assert "P1" not in ch and err == [] and fnd[0]["jenis"] == "barang_lebih"


def test_build_je_lines_per_jenis_dan_rusak():
    inv = {"fg": "1-1404", "aksesoris": "1-1402", "bahan": "1-1401"}
    contra = {"selisih": "5-1950", "rusak": "6-4300"}
    lines = eng.build_je_lines([{"kind": "fg", "value": 400000.0, "reason": ""},
                                {"kind": "aksesoris", "value": -6000.0, "reason": ""},
                                {"kind": "aksesoris", "value": -2000.0, "reason": "rusak"}], inv, contra, "Opname X")
    got = sorted((x["account_code"], x["debit"], x["credit"]) for x in lines)
    assert got == sorted([("1-1404", 400000.0, 0), ("5-1950", 0, 400000.0),
                          ("5-1950", 6000.0, 0), ("1-1402", 0, 6000.0),
                          ("6-4300", 2000.0, 0), ("1-1402", 0, 2000.0)])


def test_blocking_sheets_kontrak_scan_keluar():
    sheets = [{"id": "a", "location_id": "L", "status": "open", "date": "2026-11-02"},
              {"id": "b", "location_id": "L", "status": "open", "date": "2026-11-03"},
              {"id": "c", "location_id": "L", "status": "closed", "date": "2026-11-01"},
              {"id": "d", "location_id": "X", "status": "open", "date": "2026-11-01"}]
    assert [s["id"] for s in eng.blocking_sheets(sheets, ["L"], "2026-11-02")] == ["a"]
    assert eng.wib_date(datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)) == "2026-11-03"   # 01:30 WIB


def test_profil_dan_registri_peran_baru():
    prof = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}
    assert prof["inventory_count_variance"] == {"adjustment_expense": "5-1950", "debit_scrap_expense": "6-4300"}
    assert "inventory_count_variance" in pp.EVENT_LABELS
    cons = cb.role_consumers()
    assert cons["inventory_count_variance.adjustment_expense"][0]["code"] == "5-1950"
    assert cons["inventory_count_variance.debit_scrap_expense"][0]["code"] == "6-4300"
    assert sum(p["event_type"] == "inventory_count_variance" for p in pp.DEFAULT_PROFILES) == 1


# ═══════════════════════════ 2. alur mesin (Mongo palsu) ═══════════════════════════
def test_kain_belum_dirak_dihitung_di_lokasi_selisih_nol_dan_bin_terisi(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="L2", material_codes=[], kinds=["bahan"]))
    assert s["level"] == "lokasi" and s["location_ids"] == ["L2", "Z1"]
    env.clock.t = at(5)
    run(_count(db, s["id"], "KN1", 125, bin_id="P1"))
    run(_count(db, s["id"], "KN2", 100))
    env.clock.t = at(10)
    out = run(_flow(db, s["id"]))
    assert env.stock("KN1", "L2") == 125.0                       # dulu: 250
    assert next(p for p in db.wh_positions.docs if p["id"] == "P1")["qty"] == 125.0
    assert next(p for p in db.wh_positions.docs if p["id"] == "P2")["qty"] == 30.0     # 30 ≤ hitung 100
    assert out["summary"]["with_variance"] == 0 and env.jes == []


def test_fg_minus_dihitung_lima_jurnal_8x_wac_dan_karantina_utuh(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="LRAK"))
    env.clock.t = at(5)
    run(_count(db, s["id"], "FG1", 5))
    env.clock.t = at(9)
    out = run(_flow(db, s["id"]))
    assert env.stock("FG1", "LRAK") == 5.0 and env.stock("FG1", "LQC") == 4.0
    assert env.je_lines() == [("1-1404", 400000.0, 0), ("5-1950", 0, 400000.0)]
    assert env.jes[0]["source_module"] == "inventory_count_variance" and env.jes[0]["source_ref"] == f"opname:{s['id']}"
    assert out["status"] == "approved" and out["je_number"] == "JE-1"
    mv = db.rahaza_material_movements.docs[0]
    assert mv["type"] == "opname" and mv["qty"] == 8.0 and mv["gl_je_id"] == "je-1"


def test_tanpa_kunci_keluar_20_di_tengah_sesi(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="L2", material_codes=[], material_ids=["KN2"]))
    env.issue("KN2", "L2", 20, at(3))            # keluar sebelum dihitung
    env.clock.t = at(5)
    run(_count(db, s["id"], "KN2", 78, bin_id="P2"))
    env.issue("KN2", "L2", 5, at(7))             # keluar sesudah dihitung
    env.clock.t = at(9)
    sess = run(eng.submit(db, USER, run(eng.get_session(db, s["id"]))))
    ev = run(eng.evaluate(db, sess))["lines"][0]
    assert (ev["snapshot_qty"], ev["mutation_qty"], ev["system_qty"], ev["variance_qty"], ev["variance_value"]) == \
        (100.0, -20.0, 80.0, -2.0, -20000.0)
    run(eng.approve(db, USER, sess))
    assert env.stock("KN2", "L2") == 73.0
    assert env.je_lines() == [("1-1401", 0, 20000.0), ("5-1950", 20000.0, 0)]
    # bin ter-scan 78 dibatasi saldo akhir 73 (5 keluar sesudah dihitung) → Σ penempatan ≤ stok
    assert next(p for p in db.wh_positions.docs if p["id"] == "P2")["qty"] == 73.0


def test_aksesoris_akun_1402_dan_rusak_6300_hitung_buta_anggap_nol(env):
    db = env.db
    seed(db)
    db[stock_service.STOCK].docs.append({"id": "s7", "material_id": "KN1", "location_id": "LACC", "qty": 3.0})
    s = run(eng.create_session(db, USER, location_id="LACC", kinds=["aksesoris"], source="aksesoris"))
    assert sorted(ln["material_id"] for ln in s["lines"]) == ["AC1", "AC2"]          # kain di lokasi tak ikut
    env.clock.t = at(5)
    run(_count(db, s["id"], "AC1", 47))
    view = run(eng.session_view(db, run(eng.get_session(db, s["id"]))))
    assert view["blind"] is True and all("system_qty" not in ln and "snapshot_qty" not in ln for ln in view["lines"])
    assert {ln["material_id"]: ln["status"] for ln in view["lines"]} == {"AC1": "dihitung", "AC2": "belum"}
    with pytest.raises(HTTPException) as e:
        run(eng.submit(db, USER, run(eng.get_session(db, s["id"]))))
    assert e.value.status_code == 409 and e.value.detail["code"] == "belum_dihitung"
    assert [x["material_code"] for x in e.value.detail["belum_dihitung"]] == ["A-RES-01"]
    run(_count(db, s["id"], "AC2", 8))
    run(eng.set_line(db, run(eng.get_session(db, s["id"])), key="AC2", reason="rusak"))
    run(_flow(db, s["id"]))
    assert (env.stock("AC1", "LACC"), env.stock("AC2", "LACC"), env.stock("KN1", "LACC")) == (47.0, 8.0, 3.0)
    assert env.je_lines() == sorted([("5-1950", 6000.0, 0), ("1-1402", 0, 6000.0),
                                     ("6-4300", 2000.0, 0), ("1-1402", 0, 2000.0)])


def test_anggap_nol_menimpa_saldo(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="LACC"))
    env.clock.t = at(5)
    run(_count(db, s["id"], "AC1", 50))
    run(_flow(db, s["id"], confirm_zero=True))
    assert env.stock("AC2", "LACC") == 0.0                    # AC2 "belum" → dikonfirmasi anggap 0
    assert env.je_lines() == [("1-1402", 0, 10000.0), ("5-1950", 10000.0, 0)]


def test_approve_ditolak_selama_lembar_scan_keluar_terbuka(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="LRAK"))
    env.clock.t = at(5)
    run(_count(db, s["id"], "FG1", 5))
    sess = run(eng.submit(db, USER, run(eng.get_session(db, s["id"]))))
    assert sess["count_date"] == "2026-11-02"
    db.wh_scan_out_sheets.docs.append({"id": "sh1", "date": "2026-11-02", "location_id": "LRAK", "status": "open"})
    with pytest.raises(HTTPException) as e:
        run(eng.approve(db, USER, sess))
    assert e.value.status_code == 409 and "lembar scan keluar" in e.value.detail
    assert env.stock("FG1", "LRAK") == -3.0 and env.jes == []                      # tidak ada yang berubah
    db.wh_scan_out_sheets.docs[0]["status"] = "closed"
    assert run(eng.approve(db, USER, run(eng.get_session(db, s["id"]))))["status"] == "approved"
    assert env.stock("FG1", "LRAK") == 5.0


def test_approve_hanya_satu_penyetuju_dan_ulang_aman(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="LRAK"))
    env.clock.t = at(5)
    run(_count(db, s["id"], "FG1", 5))
    sess = run(eng.submit(db, USER, run(eng.get_session(db, s["id"]))))
    doc = next(d for d in db[eng.SESS].docs if d["id"] == s["id"])
    doc.update(status="approving", approving_at=at(4))            # penyetuju lain sedang memproses
    with pytest.raises(HTTPException) as e:
        run(eng.approve(db, USER, run(eng.get_session(db, s["id"]))))
    assert e.value.status_code == 409 and env.stock("FG1", "LRAK") == -3.0
    env.clock.t = at(20)                                          # macet ≥ 10 menit → boleh diambil ulang
    assert run(eng.approve(db, USER, run(eng.get_session(db, s["id"]))))["status"] == "approved"
    assert env.stock("FG1", "LRAK") == 5.0 and len(env.jes) == 1
    with pytest.raises(HTTPException):
        run(eng.approve(db, USER, run(eng.get_session(db, s["id"]))))   # sudah approved
    assert sess["status"] == "submitted"


def test_hitung_rak_hanya_penempatan(env):
    db = env.db
    seed(db)
    s = run(eng.create_session(db, USER, location_id="L2", sub_type="rack", sub_id="R1"))
    assert s["level"] == "rak" and [ln["key"] for ln in s["lines"]] == ["KN2@P2"]
    env.clock.t = at(5)
    run(_count(db, s["id"], "KN2", 25, bin_id="P2"))
    run(_count(db, s["id"], "KN1", 40, bin_id="P1"))           # tak tercatat di penempatan → "pindah" (bawaan)
    run(_flow(db, s["id"]))
    assert env.stock("KN1", "L2") == 125.0 and env.stock("KN2", "L2") == 100.0 and env.jes == []
    pos = {p["id"]: (p["material_id"], p["qty"]) for p in db.wh_positions.docs}
    assert pos == {"P1": ("KN1", 40.0), "P2": ("KN2", 25.0)}


def test_lokasi_karantina_dan_arsip_lama(env):
    db = env.db
    seed(db)
    with pytest.raises(HTTPException) as e:
        run(eng.create_session(db, USER, location_id="LQC"))
    assert e.value.status_code == 400 and "KARANTINA" in e.value.detail
    db[eng.SESS].docs.append({"id": "old3", "session_no": "OPN-202610-0001", "status": "submitted"})
    db[eng.LEGACY_ACC].docs.append({"id": "oldacc", "session_no": "OPNAME-0001", "domain": "accessory",
                                    "status": "pending_approval", "created_at": T0})
    for sid in ("old3", "oldacc"):
        with pytest.raises(HTTPException) as e:
            run(eng.get_session(db, sid, for_write=True))
        assert e.value.status_code == 410
    rows = run(eng.list_sessions(db))
    assert {r["id"]: r["archived"] for r in rows} == {"old3": True, "oldacc": True}
    assert [r["id"] for r in run(eng.list_sessions(db, kind="aksesoris"))] == ["oldacc"]


def test_route_lama_tetap_memakai_ssot_resolver_dan_label_lokasi():
    from routes import wms_labels as wl, wms_opname3 as op, dewi_accessories_opname as acc
    assert op._resolve_item and op._resolve_position and op.SESS == eng.SESS
    assert "approve_opname" in dir(acc) and not hasattr(acc, "_all_accessory_stock")       # mesin lama dibuang
    doc = wl.location_label_doc({"id": "L2", "code": "GD-L2", "name": "Gudang Lantai 2", "storage_role": "bahan"})
    from core import label_render as lr
    assert lr.code_of(doc, "bin") == "GD-L2" and doc["label"] == "Gudang Lantai 2"
    if lr.LABELS_OK:
        assert lr.grid_labels_pdf("bin", [doc]).getvalue()[:4] == b"%PDF"
