"""Uji unit HERMETIK Tahap 2 — paket GUDANG (gudang · cutting · material produksi), 6 Nov 2026.

Angka harapan DIHITUNG TANGAN:
  * SJ internal 2 baris (kain 5 kg dari 20, kancing 30 pcs dari 100): terbit → asal 15 / 70, dalam
    perjalanan 5 / 30 (reserved penuh, tersedia 0); diterima → tujuan 5 / 30, perjalanan 0.
  * Stok minus −5 @100, masuk 10 @120 → HPP 120, koreksi −5 × (120 − 100) = −100 (Dr 5-1950 / Cr 1-1402).
  * Cutting: diambil 10 kg, sisa kembali 2 kg, limbah 500 gram → terpakai 8 kg; stok kain 50 → 42;
    gulungan 20 → 12; nilai ke potongan 8 × 30.000 = 240.000 (bukan 300.000); limbah 0,5 kg.
  * Kebutuhan PO 10 kg; MI keluar 6 − retur 1 + cutting PO 2 = 7 → sisa 3; tersedia 1 → kurang 2.
  * Retur MI 10: baik 3 + rusak 4 → sisa bisa diretur 3 (dulu 7); pemakaian HPP tetap dikurangi 3 saja.
  * Variance: dipesan 10, diproduksi 12 → 2 pcs (ketikan 99 diabaikan) × WAC 25.000 = 50.000.

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap2_gudang.py -q
"""
import asyncio
import copy
import importlib.util
import json
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
from core import stock_service  # noqa: E402
from core import stock_transfer  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, body=None):
        self._b = body or {}
        self.query_params = {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)


# ── Mongo palsu milik berkas ini: + update ber-pipeline & filter `$expr` (dipakai stock_service) ──
class Res:
    def __init__(self, matched=0, upserted_id=None):
        self.matched_count = matched
        self.modified_count = matched
        self.upserted_id = upserted_id
        self.deleted_count = 0
        self.inserted_id = None


def ev(doc, e):
    if isinstance(e, str) and e.startswith("$"):
        v = fm._get(doc, e[1:])
        return None if v is fm._MISSING else v
    if isinstance(e, dict) and len(e) == 1 and str(next(iter(e))).startswith("$"):
        op, a = next(iter(e.items()))
        if op == "$literal":
            return a
        if op == "$ifNull":
            x = ev(doc, a[0])
            return x if x is not None else ev(doc, a[1])
        if op == "$round":
            return round(float(ev(doc, a[0]) or 0), a[1])
        if op == "$add":
            return sum(float(ev(doc, x) or 0) for x in a)
        if op == "$subtract":
            return float(ev(doc, a[0]) or 0) - float(ev(doc, a[1]) or 0)
        if op == "$max":
            return max(float(ev(doc, x) or 0) for x in a)
        if op == "$gte":
            return float(ev(doc, a[0]) or 0) >= float(ev(doc, a[1]) or 0)
        raise NotImplementedError(op)
    return e


def _apply(d, upd):
    for k, v in (upd.get("$set") or {}).items():
        fm._set_path(d, k, copy.deepcopy(v))
    for k, v in (upd.get("$inc") or {}).items():
        cur = fm._get(d, k)
        fm._set_path(d, k, (0 if cur is fm._MISSING else cur) + v)
    for k, v in (upd.get("$push") or {}).items():
        cur = fm._get(d, k)
        fm._set_path(d, k, (cur if isinstance(cur, list) else []) + [copy.deepcopy(v)])
    for k in (upd.get("$unset") or {}):
        d.pop(k, None)


class Coll(fm.FakeCollection):
    @staticmethod
    def _hit(d, q):
        q = dict(q or {})
        ex = q.pop("$expr", None)
        return fm.match(d, q) and (ex is None or bool(ev(d, ex)))

    def find(self, q=None, projection=None):
        return fm.FakeCursor([d for d in self.docs if self._hit(d, q)])

    async def find_one(self, q=None, projection=None, **kw):
        for d in self.docs:
            if self._hit(d, q):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, q=None):
        return sum(1 for d in self.docs if self._hit(d, q))

    async def update_one(self, q, upd, upsert=False, **kw):
        target = next((d for d in self.docs if self._hit(d, q)), None)
        created = False
        if target is None:
            if not upsert:
                return Res(0)
            target = {k: v for k, v in (q or {}).items() if not k.startswith("$") and not isinstance(v, dict)}
            self.docs.append(target)
            created = True
        if isinstance(upd, list):
            for stage in upd:
                vals = {k: ev(target, v) for k, v in stage["$set"].items()}
                for k, v in vals.items():
                    fm._set_path(target, k, copy.deepcopy(v))
        else:
            if created:
                target.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
            _apply(target, upd)
        return Res(0 if created else 1, upserted_id="baru" if created else None)

    async def update_many(self, q, upd):
        n = 0
        for d in self.docs:
            if self._hit(d, q):
                _apply(d, upd)
                n += 1
        return Res(n)


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Coll(name)
        return self._cols[name]


def _noop():
    async def f(*a, **k):
        return None
    return f


@pytest.fixture
def posting(monkeypatch):
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        jes.append({"id": f"je-{len(jes) + 1}", "source_module": mod, "source_ref": ref, "lines": lines})
        return {"ok": True, "je_id": jes[-1]["id"], "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", _noop())
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def lines(i=-1):
        return sorted((ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in jes[i]["lines"])
    return types.SimpleNamespace(jes=jes, lines=lines)


def _row(db, mid, loc):
    return next((r for r in db[stock_service.STOCK].docs if r["material_id"] == mid and r["location_id"] == loc), {})


def _base_db():
    db = DB()
    db.rahaza_locations.docs += [{"id": "L1", "code": "GD-A", "name": "Gudang A", "storage_role": "bahan", "active": True},
                                 {"id": "L2", "code": "GD-B", "name": "Gudang B", "storage_role": "bahan", "active": True}]
    db.rahaza_materials.docs += [
        {"id": "M1", "code": "K-01", "name": "Kain Katun", "type": "fabric", "unit": "kg", "unit_cost": 30000.0,
         "active": True},
        {"id": "M2", "code": "A-KCG", "name": "Kancing", "type": "accessory", "unit": "pcs", "unit_cost": 100.0,
         "active": True}]
    db[stock_service.STOCK].docs += [
        {"id": "s1", "material_id": "M1", "location_id": "L1", "qty": 20.0, "reserved_quantity": 0.0},
        {"id": "s2", "material_id": "M2", "location_id": "L1", "qty": 100.0, "reserved_quantity": 0.0}]
    return db


# ═════════════════════ GUDANG 1 · SJ internal = transfer antar lokasi ═════════════════════
def _dn_env(monkeypatch, db):
    import routes.wms_delivery_notes as dn

    async def auth(_r):
        return WH

    async def num(db_, key, ctx=None, requested=""):
        return f"SJ-INTERNAL/2026/11/{len(db_.wh_delivery_notes.docs) + 1:04d}"
    monkeypatch.setattr(dn, "require_auth", auth)
    monkeypatch.setattr(dn, "get_db", lambda: db)
    monkeypatch.setattr(dn, "issue_number", num)
    return dn


def _sj_in(dn, qty1=5.0, qty2=30.0, **kw):
    return dn.SJIn(sj_type="SJ-INTERNAL", recipient_name="Gudang B", from_location_id=kw.get("src", "L1"),
                   to_location_id=kw.get("dst", "L2"),
                   lines=[dn.SJLine(description="kain", qty=qty1, unit="kg", material_id="M1"),
                          dn.SJLine(description="kancing", qty=qty2, unit="pcs", material_code="A-KCG")])


def test_sj_internal_terbit_keluar_ke_perjalanan_lalu_diterima_masuk_tujuan(monkeypatch):
    db = _base_db()
    dn = _dn_env(monkeypatch, db)
    sj = run(dn.create_sj(_sj_in(dn), Req()))["sj"]
    assert sj["stock_mode"] == "transfer" and [ln["material_id"] for ln in sj["lines"]] == ["M1", "M2"]
    assert _row(db, "M1", "L1")["qty"] == 20.0                       # draft belum menyentuh stok
    out = run(dn.issue_sj(sj["id"], dn.IssueIn(), Req()))
    assert out["stock_moved"] is True
    transit = out["sj"]["transit_location_id"]
    assert _row(db, "M1", "L1")["qty"] == 15.0 and _row(db, "M2", "L1")["qty"] == 70.0   # BARIS 2 ikut keluar
    t1, t2 = _row(db, "M1", transit), _row(db, "M2", transit)
    assert (t1["qty"], t1["available_quantity"]) == (5.0, 0.0) and (t2["qty"], t2["available_quantity"]) == (30.0, 0.0)
    with pytest.raises(HTTPException):                               # terbit ulang ditolak
        run(dn.issue_sj(sj["id"], dn.IssueIn(), Req()))
    run(dn.receive_sj(sj["id"], dn.ReceiveIn(), Req()))
    assert _row(db, "M1", "L2")["qty"] == 5.0 and _row(db, "M2", "L2")["qty"] == 30.0
    assert _row(db, "M1", transit)["qty"] == 0.0 and _row(db, "M2", transit)["qty"] == 0.0
    doc = db.wh_delivery_notes.docs[0]
    assert doc["status"] == "received" and doc.get("stock_in_at")
    kinds = sorted(m["notes"].split("—")[-1].strip() for m in db.rahaza_material_movements.docs)
    assert len(db.rahaza_material_movements.docs) == 4 and "diterima di tujuan" in kinds
    # tidak ada antrean "Scan-Out" lama
    assert db.wh_pending_movements.docs == []


def test_sj_internal_stok_kurang_ditolak_tanpa_stok_bergerak_dan_batal_kembali(monkeypatch):
    db = _base_db()
    dn = _dn_env(monkeypatch, db)
    # 10 Nov 2026: qty melebihi stok asal sudah ditolak saat BUAT (draf tidak tercipta)
    with pytest.raises(HTTPException) as e:
        run(dn.create_sj(_sj_in(dn, qty1=50.0), Req()))
    assert e.value.status_code == 400 and "tidak cukup" in e.value.detail and db.wh_delivery_notes.docs == []
    # …dan dicek lagi saat TERBIT (stok bisa berkurang di antara buat dan terbit)
    sj = run(dn.create_sj(_sj_in(dn), Req()))["sj"]
    _row(db, "M1", "L1")["qty"] = 3.0
    with pytest.raises(HTTPException) as e:
        run(dn.issue_sj(sj["id"], dn.IssueIn(), Req()))
    assert e.value.status_code == 400 and "tidak cukup" in e.value.detail
    assert db.wh_delivery_notes.docs[0]["status"] == "draft"
    assert _row(db, "M2", "L1")["qty"] == 100.0
    run(dn.delete_sj(sj["id"], Req()))
    _row(db, "M1", "L1")["qty"] = 20.0
    assert _row(db, "M1", "L1")["qty"] == 20.0 and _row(db, "M2", "L1")["qty"] == 100.0
    # SJ lain terbit lalu DIBATALKAN → stok kembali ke asal
    sj2 = run(dn.create_sj(_sj_in(dn), Req()))["sj"]
    run(dn.issue_sj(sj2["id"], dn.IssueIn(), Req()))
    run(dn.cancel_sj(sj2["id"], dn.CancelIn(reason="batal kirim"), Req()))
    assert _row(db, "M1", "L1")["qty"] == 20.0 and _row(db, "M2", "L1")["qty"] == 100.0
    transit = db.wh_delivery_notes.docs[-1]["transit_location_id"]
    assert _row(db, "M1", transit)["qty"] == 0.0 and _row(db, "M1", transit)["reserved_quantity"] == 0.0


def test_sj_internal_validasi_lokasi_dan_barang_master(monkeypatch):
    db = _base_db()
    dn = _dn_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(dn.create_sj(_sj_in(dn, src="L1", dst="L1"), Req()))
    assert "tidak boleh sama" in e.value.detail
    bad = dn.SJIn(sj_type="SJ-INTERNAL", recipient_name="x", from_location_id="L1", to_location_id="L2",
                  lines=[dn.SJLine(description="barang ketikan", qty=1)])
    with pytest.raises(HTTPException) as e:
        run(dn.create_sj(bad, Req()))
    assert "dari master" in e.value.detail and db.wh_delivery_notes.docs == []
    # 10 Nov 2026 (owner): SJ CMT tidak lagi dibuat di Gudang — ditolak dengan menu asalnya, stok diam
    cmt = dn.SJIn(sj_type="SJ-CMT", recipient_name="CMT A", lines=[dn.SJLine(description="kain", qty=3)])
    with pytest.raises(HTTPException) as e:
        run(dn.create_sj(cmt, Req()))
    assert e.value.status_code == 400 and "Produksi › Kirim ke CMT" in e.value.detail
    assert db.wh_delivery_notes.docs == [] and _row(db, "M1", "L1")["qty"] == 20.0


# ═════════════════════ GUDANG 3 · transfer tidak bisa memindah stok karantina ═════════════════════
def test_transfer_stok_karantina_dan_tereserve_ditolak(monkeypatch):
    import routes.rahaza_inventory_stock as ris
    from core import quarantine as qmod
    db = _base_db()

    async def admin(_r):
        return WH
    monkeypatch.setattr(ris, "_require_admin", admin)
    monkeypatch.setattr(ris, "get_db", lambda: db)
    qloc = run(qmod.get_quarantine_location_id(db))
    db[stock_service.STOCK].docs.append({"id": "sq", "material_id": "M1", "location_id": qloc, "qty": 5.0,
                                         "reserved_quantity": 5.0, "quarantine": True, "blocked": True})
    with pytest.raises(HTTPException) as e:
        run(ris.material_transfer(Req({"material_id": "M1", "from_location_id": qloc, "to_location_id": "L2", "qty": 5})))
    assert e.value.status_code == 400 and "karantina" in e.value.detail
    assert _row(db, "M1", qloc)["qty"] == 5.0
    with pytest.raises(HTTPException) as e:                          # transfer MASUK karantina juga ditolak
        run(ris.material_transfer(Req({"material_id": "M1", "from_location_id": "L1", "to_location_id": qloc, "qty": 1})))
    assert "karantina" in e.value.detail
    _row(db, "M1", "L1")["reserved_quantity"] = 18.0                 # 18 ter-reserve → tersedia 2
    with pytest.raises(HTTPException) as e:
        run(ris.material_transfer(Req({"material_id": "M1", "from_location_id": "L1", "to_location_id": "L2", "qty": 5})))
    assert "tersedia 2" in e.value.detail
    run(ris.material_transfer(Req({"material_id": "M1", "from_location_id": "L1", "to_location_id": "L2", "qty": 2})))
    assert _row(db, "M1", "L1")["qty"] == 18.0 and _row(db, "M1", "L2")["qty"] == 2.0


# ═════════════════════ GUDANG 2 · put-away per zona, tanpa karantina & minus ═════════════════════
def test_putaway_belum_dirak_per_zona_dan_bin_wajib_satu_zona(monkeypatch):
    import routes.shared as shared
    import routes.wms_putaway as pw
    from core import quarantine as qmod
    db = _base_db()
    db[stock_service.STOCK].docs = []
    db.wh_zones.docs += [{"id": "Z1", "code": "ZN-KAIN", "name": "Kain", "active": True},
                         {"id": "Z2", "code": "ZN-02", "name": "Zona 2", "active": True}]
    db.wh_positions.docs += [{"id": "B1", "zone_id": "Z1", "barcode": "B1", "label": "B1", "qty": 0},
                             {"id": "B2", "zone_id": "Z2", "barcode": "B2", "label": "B2", "qty": 0}]
    qloc = run(qmod.get_quarantine_location_id(db))
    db[stock_service.STOCK].docs += [
        {"id": "a", "material_id": "M1", "location_id": "Z1", "qty": 10.0},
        {"id": "b", "material_id": "M1", "location_id": qloc, "qty": 5.0, "reserved_quantity": 5.0, "quarantine": True},
        {"id": "c", "material_id": "M1", "location_id": "Z2", "qty": -3.0}]

    async def auth(_r):
        return WH

    async def perm(*a, **k):
        return WH
    monkeypatch.setattr(pw, "require_auth", auth)
    monkeypatch.setattr(pw, "get_db", lambda: db)
    monkeypatch.setattr(pw, "log_activity", _noop())
    monkeypatch.setattr(shared, "require_perm", perm)
    pend = run(pw.list_pending(Req(), search=None))
    item = pend["groups"]["bahan"][0]
    assert item["unshelved"] == 10.0 and [z["zone_id"] for z in item["zones"]] == ["Z1"]  # dulu 10 + 5 − 3 = 12
    with pytest.raises(HTTPException) as e:
        run(pw.place(pw.PlaceIn(material_id="M1", qty=4, position_id="B2"), Req()))
    assert "tidak berada di zona" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(pw.place(pw.PlaceIn(material_id="M1", qty=11, position_id="B1"), Req()))
    assert "melebihi" in e.value.detail
    out = run(pw.place(pw.PlaceIn(material_id="M1", qty=10, position_id="B1"), Req()))
    assert out["remaining_unshelved"] == 0.0


# ═════════════════════ GUDANG 4 · rata-rata bergerak kain/aksesoris saat stok minus ═════════════════════
def test_rata_rata_stok_minus_jurnal_koreksi(posting):
    from core import accessory_valuation as av
    assert av.negative_stock_adjustment(-5, 100, 120) == -100.0
    assert av.negative_stock_adjustment(-5, 0, 120) == -600.0       # keluar saat HPP 0 → dikredit penuh
    assert av.negative_stock_adjustment(5, 100, 120) == 0.0
    assert av.negative_stock_adjustment(-5, 100, 0) == 0.0          # harga masuk kosong: HPP tidak berubah
    db = _base_db()
    res = run(av.apply_receipt_cost(db, "M2", 10, 120, qty_before=-5))
    assert res["new_unit_cost"] == 120.0 and res["adjustment_value"] == -100.0
    assert posting.jes[-1]["source_module"] == "material_wac_adjust"
    assert posting.lines() == [("1-1402", 0, 100.0), ("5-1950", 100.0, 0)]
    res = run(av.apply_receipt_cost(db, "M1", 10, 33000, qty_before=-2))   # kain: −2 × 3.000 = −6.000
    assert posting.lines() == [("1-1401", 0, 6000.0), ("5-1950", 6000.0, 0)]
    n = len(posting.jes)
    run(av.apply_receipt_cost(db, "M2", 10, 150, qty_before=20))     # stok positif: tanpa jurnal koreksi
    assert len(posting.jes) == n


# ═════════════════════ GUDANG 5 · scan keluar: antrean gagal di server, tidak pindah lembar ═════════════════════
def _so_db(day):
    db = _base_db()
    db.wh_scan_out_sheets.docs.append({"id": "SH1", "number": "SKP-1", "seq": 1, "date": day, "location_id": "L1",
                                       "location_code": "GD-A", "status": "open"})
    db.wh_scan_out_lines.docs.append({"id": "F1", "client_scan_id": "c1", "sheet_id": "SH1", "sheet_number": "SKP-1",
                                      "date": day, "location_id": "L1", "location_code": "GD-A", "kind": "scan",
                                      "qty": 1, "status": "failed", "claim_at": None, "operator_id": "u-gd",
                                      "sku": "SKU-1", "material_id": "FG1", "locked": False,
                                      "scanned_at": datetime.now(timezone.utc)})
    return db


def test_scan_gagal_tetap_di_lembar_saat_tutup_dan_bisa_dikirim_ulang(monkeypatch):
    import utils.notif_unified as nu
    from core import scan_out as so
    day = so.today_str()
    db = _so_db(day)

    async def still_fails(db_, line, actor):
        raise so.ScanOutError(500, "WAC gagal")
    monkeypatch.setattr(so, "_process", still_fails)
    monkeypatch.setattr(nu, "resolve_for_source", _noop())
    out = run(so.close_sheet(db, "SH1", user=WH))
    assert out["failed_lines"] == 1 and out["moved_lines"] == 0
    assert len(db.wh_scan_out_sheets.docs) == 1                       # dulu: lembar baru berisi baris gagal
    assert db.wh_scan_out_lines.docs[0]["sheet_id"] == "SH1"
    assert [ln["id"] for ln in run(so.retry_queue(db, location_id="L1"))] == ["F1"]
    assert run(so.retry_queue(db, location_id="L1", operator_id="orang-lain")) == []

    async def ok(db_, line, actor):
        await db_.wh_scan_out_lines.update_one({"id": line["id"]}, {"$set": {"status": "active", "claim_at": None}})
        return {**line, "status": "active"}

    async def number(db_, day_, code, seq):
        return f"SKP-1-{seq}"
    monkeypatch.setattr(so, "_process", ok)
    monkeypatch.setattr(so, "sheet_number_for", number)
    with pytest.raises(so.ScanOutError):                              # petugas lain tidak boleh
        run(so.retry_line(db, "F1", user={"id": "lain", "name": "Lain"}))
    res = run(so.retry_line(db, "F1", user=WH))
    assert res["result"] == "accepted"
    ln = db.wh_scan_out_lines.docs[0]
    assert ln["status"] == "active" and ln["sheet_id"] != "SH1"       # baru pindah sesudah berhasil
    assert run(so.retry_queue(db, location_id="L1")) == []


def test_batalkan_scan_gagal_membalik_langkah_yang_sudah_jalan(monkeypatch):
    from core import fg_cost_layers as fcl
    from core import scan_out as so
    db = _so_db(so.today_str())
    db[stock_service.STOCK].docs.append({"id": "sf", "material_id": "FG1", "location_id": "L1", "qty": 4.0})
    db.rahaza_stock_ledger.docs.append({"id": "lg", "op": "issue", "ref": {"type": so.REF_SCAN, "line_id": "F1"},
                                        "qty_after": 4.0})
    db[fcl.CONSUMPTIONS].docs.append({"id": "cs", "ref": {"type": so.REF_SCAN, "line_id": "F1"},
                                      "unit_cost": 50.0, "components": {"material": 50.0}})
    pushed = []

    async def push(db_, **kw):
        pushed.append(kw)
        return {"id": "ly"}
    monkeypatch.setattr(fcl, "push_layer", push)
    run(so.discard_failed_line(db, "F1", user=WH))
    assert _row(db, "FG1", "L1")["qty"] == 5.0                       # stok yang sempat terpotong kembali
    assert pushed[0]["unit_cost"] == 50.0 and pushed[0]["qty"] == 1
    assert db.wh_scan_out_lines.docs[0]["status"] == "voided"


def test_opname_ditahan_lembar_closing_dan_baris_gagal():
    from core import opname_engine as eng
    day = "2026-11-06"
    db = _so_db(day)
    db.wh_scan_out_sheets.docs[0]["status"] = "closing"
    sess = {"session_no": "OPN-1", "location_id": "L1", "location_code": "GD-A"}
    with pytest.raises(HTTPException) as e:
        run(eng.check_scan_out_sheets(db, sess, day))
    assert "TERBUKA" in e.value.detail                                # dulu `closing` lolos
    assert [s["id"] for s in eng.blocking_sheets(db.wh_scan_out_sheets.docs, ["L1"], day)] == ["SH1"]
    db.wh_scan_out_sheets.docs[0]["status"] = "closed"
    with pytest.raises(HTTPException) as e:
        run(eng.check_scan_out_sheets(db, sess, day))
    assert "gagal diproses" in e.value.detail
    db.wh_scan_out_lines.docs[0]["status"] = "voided"
    run(eng.check_scan_out_sheets(db, sess, day))                     # tidak ada lagi yang menahan


# ═════════════════════ GUDANG 6 · nilai Retur Fisik = HPP saat scan keluar ═════════════════════
def test_retur_fisik_dinilai_hpp_saat_scan_keluar(monkeypatch):
    from core import fg_cost_layers as fcl
    from core import returns_bridge as rb
    db = DB()
    t0 = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)
    db.wh_scan_out_lines.docs += [
        {"id": "s-old", "material_id": "FG1", "kind": "scan", "status": "active", "unit_cost": 50.0, "qty": 2,
         "components": {"material": 80.0, "labor": 20.0}, "scanned_at": t0, "sheet_number": "SKP-A"},
        {"id": "s-late", "material_id": "FG1", "kind": "scan", "status": "active", "unit_cost": 90.0, "qty": 1,
         "components": {"material": 90.0}, "scanned_at": t0 + timedelta(days=5)}]
    calls = types.SimpleNamespace(push=[], je=[], loss=[])

    async def wac(db_, mid, **kw):
        return {"unit_cost": 70.0, "components": {"material": 70.0}}

    async def push(db_, **kw):
        calls.push.append(kw)
        return {"id": "ly1"}

    async def je(db_, ret, qty, uc, user, **kw):
        calls.je.append(uc)
        return {"ok": True, "je_id": "j1", "je_number": "JE-1"}

    async def loss(db_, ret, qty, uc, user, disposed=False, **kw):
        calls.loss.append(uc)
        return {"ok": True, "je_id": "j2", "je_number": "JE-2"}
    monkeypatch.setattr(fcl, "wac_state", wac)
    monkeypatch.setattr(fcl, "push_layer", push)
    monkeypatch.setattr(rp, "post_marketplace_return_restock", je)
    monkeypatch.setattr(rp, "post_return_damaged_loss", loss)
    ret = {"id": "W1", "return_code": "RET-1", "received_at": "2026-11-03T00:00:00+00:00"}
    out = run(rb._value_restock(db, ret, "FG1", 1, WH))
    assert out["hpp_unit_cost"] == 50.0 and out["hpp_basis"] == "scan_out" and out["hpp_scan_line_id"] == "s-old"
    assert calls.push[0]["unit_cost"] == 50.0 and calls.je == [50.0]
    dmg = run(rb._value_damaged(db, ret, "FG1", 2, WH))
    assert dmg["loss_unit_cost"] == 50.0 and dmg["loss_amount"] == 100.0 and dmg["loss_basis"] == "scan_out"
    # belum pernah di-scan keluar → cadangan WAC hari keputusan
    out = run(rb._value_restock(db, {**ret, "id": "W2"}, "FG-LAIN", 1, WH))
    assert out["hpp_unit_cost"] == 70.0 and out["hpp_basis"] == "wac"


# ═════════════════════ GUDANG 7 + CUTTING 2/3/4 · progres cutting ═════════════════════
def _cut_db():
    db = _base_db()
    db[stock_service.STOCK].docs = [{"id": "s1", "material_id": "M1", "location_id": "L1", "qty": 50.0}]
    db.rahaza_materials.docs += [
        {"id": "P1", "code": "CUT-MDL-RED-M", "name": "Potongan M", "type": "fabric", "unit": "pcs",
         "is_cut_panel": True, "model_id": "MOD1", "size_code": "M", "unit_cost": 0.0, "active": True},
        {"id": "P2", "code": "CUT-MD2-RED-M", "name": "Potongan 2", "type": "fabric", "unit": "pcs",
         "is_cut_panel": True, "model_id": "MOD2", "size_code": "M", "unit_cost": 0.0, "active": True}]
    db.wh_fabric_rolls.docs += [
        {"id": "R1", "roll_no": "R-0001", "material_id": "M1", "uom": "kg", "weight_kg": 20.0, "remaining_kg": 20.0,
         "status": "in_stock", "location_id": "L1", "location_name": "Gudang A"},
        {"id": "R2", "roll_no": "R-0002", "material_id": "M1", "uom": "kg", "weight_kg": 30.0, "remaining_kg": 30.0,
         "status": "in_stock", "location_id": "L2", "location_name": "Gudang B"}]
    db.cutting_orders.docs.append({
        "id": "O1", "number": "CUT-2026-0001", "status": "in_progress", "input_material_id": "M1",
        "input_material_code": "K-01", "input_material_name": "Kain Katun", "input_unit": "kg", "location_id": "L1",
        "location_name": "Gudang A", "output_material_id": "P1", "output_material_code": "CUT-MDL-RED-M",
        "output_material_name": "Potongan M", "roll_ids": [], "consumed_input_qty": 0.0, "produced_qty": 0.0,
        "waste_qty": 0.0, "style_name": "Model 1"})
    db.rahaza_models.docs += [{"id": "MOD1", "code": "MDL", "name": "Model 1", "active": True},
                              {"id": "MOD2", "code": "MD2", "name": "Model 2", "active": True}]
    db.rahaza_sizes.docs.append({"id": "S1", "code": "M"})
    db.rahaza_model_variants.docs.append({"id": "V1", "model_id": "MOD1", "size_id": "S1", "size_code": "M",
                                          "color_name": "Merah", "color_code": "RED", "sku": "MDL-RED-M"})
    return db


def _cut_env(monkeypatch, db):
    import routes.cutting as cut
    from core import cutting_material_issue as cmi
    from core import negative_stock

    async def user(_r):
        return WH

    async def no(_db):
        return False

    async def number(*a, **k):
        return "CUT-2026-0002"

    async def boms(db_, model_id, size_id, color=None):
        return {"materials": [{"material_id": "P1" if model_id == "MOD1" else "P2", "is_cut_panel": True}]}
    monkeypatch.setattr(cut, "_require_cutting_user", user)
    monkeypatch.setattr(cut, "require_auth", user)
    monkeypatch.setattr(cut, "get_db", lambda: db)
    monkeypatch.setattr(cut, "log_activity", _noop())
    monkeypatch.setattr(cut, "gen_prefixed_number", number)
    monkeypatch.setattr(negative_stock, "allowed", no)
    monkeypatch.setattr(cmi, "doc_for_progress", _noop())
    monkeypatch.setattr(cut.product_costing, "find_active_bom", boms)
    return cut


def test_cutting_sisa_kain_kembali_ke_stok_limbah_bersatuan_mengurangi_gulungan(monkeypatch):
    db = _cut_db()
    cut = _cut_env(monkeypatch, db)
    out = run(cut.add_progress("O1", Req({"input_consumed": 10, "output_qty": 20, "leftover_qty": 2,
                                          "waste_qty": 500, "waste_uom": "gram", "roll_ids": ["R1"]})))
    assert _row(db, "M1", "L1")["qty"] == 42.0                       # diambil 10 − sisa 2 = 8 kg terpakai
    assert db.wh_fabric_rolls.docs[0]["remaining_kg"] == 12.0
    prog = db.cutting_progress.docs[0]
    assert (prog["input_taken"], prog["leftover_qty"], prog["input_consumed"], prog["waste_qty"]) == (10.0, 2.0, 8.0, 0.5)
    assert prog["value_out"] == 240000.0                             # sisa tidak ikut nilai potongan
    assert out["consumed_input_qty"] == 8.0 and out["leftover_qty"] == 2.0 and out["waste_qty"] == 0.5
    assert _row(db, "P1", "L1")["qty"] == 20.0


def test_cutting_validasi_sisa_limbah_gulungan_gudang_lain_dan_satuan_gram(monkeypatch):
    db = _cut_db()
    cut = _cut_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(cut.add_progress("O1", Req({"input_consumed": 5, "output_qty": 5, "leftover_qty": 3, "waste_qty": 3,
                                        "roll_ids": ["R1"]})))
    assert "melebihi kain yang diambil" in e.value.detail
    with pytest.raises(HTTPException) as e:                          # gulungan di Gudang B, order di Gudang A
        run(cut.add_progress("O1", Req({"input_consumed": 5, "output_qty": 5, "roll_ids": ["R2"]})))
    assert "gudang lain" in e.value.detail
    assert _row(db, "M1", "L1")["qty"] == 50.0                       # ditolak SEBELUM stok dipotong
    rolls = run(cut.list_rolls(Req(), material_id="M1", location_id="L1"))
    assert [r["id"] for r in rolls["items"]] == ["R1"] and rolls["other_location_count"] == 1
    run(cut.add_progress("O1", Req({"input_consumed": 3000, "input_uom": "gram", "output_qty": 5, "roll_ids": ["R1"]})))
    assert _row(db, "M1", "L1")["qty"] == 47.0 and db.wh_fabric_rolls.docs[0]["remaining_kg"] == 17.0


# ═════════════════════ CUTTING 1/5/6 · ukuran wajib, kode ketikan, ubah model ═════════════════════
def _order_body(**kw):
    return {"input_material_id": "M1", "location_id": "L1", "planned_input_qty": 5, "planned_output_qty": 10,
            "model_id": "MOD1", **kw}


def test_cutting_ukuran_wajib_kode_ketikan_dan_ubah_model_mengganti_output(monkeypatch):
    db = _cut_db()
    cut = _cut_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(_order_body())))
    assert "Ukuran wajib" in e.value.detail

    async def no_bom(*a, **k):
        return None
    monkeypatch.setattr(cut.product_costing, "find_active_bom", no_bom)
    with pytest.raises(HTTPException) as e:                          # kode ketikan menunjuk KAIN, bukan potongan
        run(cut.create_order(Req(_order_body(variant_id="V1", output_material_code="K-01"))))
    assert "bukan potongan" in e.value.detail
    with pytest.raises(HTTPException):                               # potongan model LAIN juga ditolak
        run(cut.create_order(Req(_order_body(variant_id="V1", output_material_code="CUT-MD2-RED-M"))))
    _cut_env(monkeypatch, db)                                         # BOM kembali tersedia
    o = run(cut.create_order(Req(_order_body(variant_id="V1"))))
    assert (o["output_material_id"], o["size_id"], o["output_size"]) == ("P1", "S1", "M")
    db.cutting_orders.docs[-1]["status"] = "draft"
    upd = run(cut.update_order(o["id"], Req({"model_id": "MOD2", "size_id": "S1"})))
    assert upd["model_id"] == "MOD2" and upd["output_material_id"] == "P2" and upd["variant_id"] == ""


def test_cutting_tautan_baris_po_opsional_menentukan_ukuran(monkeypatch):
    db = _cut_db()
    cut = _cut_env(monkeypatch, db)
    db.production_pos.docs.append({"id": "PO1", "po_number": "PO-1", "status": "In Production"})
    db.po_items.docs.append({"id": "pi1", "po_id": "PO1", "model_id": "MOD1", "size_id": "S1", "size": "M",
                             "qty": 10, "rahaza_variant_id": "V1"})
    o = run(cut.create_order(Req(_order_body(po_item_id="pi1"))))
    assert (o["po_item_id"], o["po_number"], o["size_id"], o["variant_id"]) == ("pi1", "PO-1", "S1", "V1")
    lines = run(cut.list_po_lines(Req(), model_id="MOD1"))
    assert [ln["id"] for ln in lines] == ["pi1"]
    db.production_pos.docs[0]["status"] = "Closed"
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(_order_body(po_item_id="pi1"))))
    assert "sudah ditutup" in e.value.detail


# ═════════════════════ PRODUKSI 1 · kebutuhan material per PO dikurangi yang sudah keluar ═════════════════════
def test_kebutuhan_material_po_dikurangi_yang_sudah_keluar(monkeypatch):
    import routes.rahaza_material_requirements as mr
    db = _base_db()
    db[stock_service.STOCK].docs = [{"id": "s1", "material_id": "M1", "location_id": "L1", "qty": 1.0}]
    db.production_pos.docs.append({"id": "PO1", "po_number": "PO-1", "business_type": "internal"})
    db.po_items.docs.append({"id": "pi1", "po_id": "PO1", "model_id": "MOD1", "size_id": "S1", "qty": 10})
    db.rahaza_material_issues.docs += [
        {"id": "mi1", "production_po_id": "PO1", "status": "issued",
         "items": [{"material_id": "M1", "qty_issued": 6.0, "qty_returned": 1.0}]},
        {"id": "mi2", "production_po_id": "PO1", "status": "pending_approval",
         "items": [{"material_id": "M1", "qty_issued": 0, "qty_required": 4.0}]}]
    db.cutting_orders.docs.append({"id": "c1", "po_id": "PO1", "status": "completed", "input_material_id": "M1",
                                   "consumed_input_qty": 2.0})

    async def auth(_r):
        return WH

    async def bom(db_, model_id, size_id, color=None, color_code=None):  # Tahap 9: _active_bom kini juga menerima color_code
        return {"id": "B1", "version": 1}

    async def ensure(db_, b):
        return [{"material_id": "M1", "code": "K-01", "name": "Kain", "qty_base": 1.0, "unit_base": "kg",
                 "unit": "kg"}], []
    monkeypatch.setattr(mr, "require_auth", auth)
    monkeypatch.setattr(mr, "get_db", lambda: db)
    monkeypatch.setattr(mr, "_find_active_bom", bom)
    # Tahap 9: sumber PO memakai hitungan bersama `material_issue_engine.bom_need_for_lines`
    import core.material_issue_engine as mie
    monkeypatch.setattr(mie, "_active_bom", bom)
    monkeypatch.setattr(mr.bom_uom, "ensure_uom", ensure)
    out = run(mr.aggregate_material_requirements(Req({"po_id": "PO1", "include_cost": False})))
    row = out["aggregated"][0]
    assert (row["total_required"], row["issued"], row["remaining_required"], row["shortfall"]) == (10.0, 7.0, 3.0, 2.0)
    # sumber baris manual: tidak ada pengurang
    out = run(mr.aggregate_material_requirements(Req({"lines": [{"model_id": "MOD1", "size_id": "S1", "qty_pcs": 10}],
                                                      "include_cost": False})))
    assert out["aggregated"][0]["issued"] is None and out["aggregated"][0]["shortfall"] == 9.0


# ═════════════════════ PRODUKSI 2 · retur rusak/sisa ikut mengurangi batas retur ═════════════════════
def test_batas_retur_ikut_berkurang_oleh_retur_rusak():
    import routes.production_material_returns as pmr
    mi = {"items": [{"material_id": "K", "qty_issued": 10}]}
    after = pmr.mi_after_return(mi, {"K": 3}, {"K": 4})
    it = after["items"][0]
    assert (it["qty_returned"], it["qty_returned_nonstock"]) == (3.0, 4.0)
    assert pmr.mi_returnable(after) == {"K": 3.0}                   # dulu 7 (rusak tidak dihitung)
    assert after["qty_returned_total"] == 3.0 and after["return_status"] == "partial"
    full = pmr.mi_after_return(after, {}, {"K": 5})                  # dibatasi sisa 3
    assert full["items"][0]["qty_returned_nonstock"] == 7.0 and full["return_status"] == "full"
    assert pmr.mi_after_return({"items": [{"material_id": "K", "qty_issued": 5}]}, {"K": 5})["return_status"] == "full"


def test_terima_retur_rusak_memperbarui_baris_mi(monkeypatch):
    import routes.production_material_returns as pmr
    db = _base_db()
    db.rahaza_material_issues.docs.append({"id": "mi1", "mi_number": "MI-1", "status": "issued",
                                           "items": [{"material_id": "M1", "qty_issued": 10.0,
                                                      "unit_cost_applied": 30000.0}]})
    db.production_material_returns.docs.append({"id": 7, "ref_no": "RET-7", "status": "approved",
                                                "material_issue_id": "mi1",
                                                "items": [{"material_id": "M1", "material_code": "K-01",
                                                           "qty_returned": 4.0, "condition": "damaged"}]})

    async def auth(_r):
        return {**WH, "role": "superadmin"}
    monkeypatch.setattr(pmr, "require_auth", auth)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    monkeypatch.setattr(pmr, "log_activity", _noop())
    run(pmr.receive_return(Req(), "7", pmr.ActionModel(note="")))
    it = db.rahaza_material_issues.docs[0]["items"][0]
    assert it.get("qty_returned_nonstock") == 4.0 and not it.get("qty_returned")
    assert pmr.mi_returnable(db.rahaza_material_issues.docs[0]) == {"M1": 6.0}
    assert _row(db, "M1", "L1")["qty"] == 20.0                      # rusak tidak kembali ke stok


# ═════════════════════ PRODUKSI 3 · baris manual Terima FG wajib dari master ═════════════════════
def test_baris_manual_terima_fg_wajib_dari_master(monkeypatch):
    import routes.dewi_cmt_packing as cp
    db = DB()
    db.cmt_receipts.docs.append({"id": "RC1", "status": cp.ST_QC})
    db.rahaza_materials.docs.append({"id": "FG1", "type": "fg", "code": "SKU-1", "name": "Kaos M",
                                     "color_name": "Merah", "size_code": "M"})

    async def auth(_r):
        return WH

    async def novariant(db_, **kw):
        return None
    monkeypatch.setattr(cp, "require_auth", auth)
    monkeypatch.setattr(cp, "get_db", lambda: db)
    monkeypatch.setattr(cp, "resolve_variant", novariant)
    monkeypatch.setattr(cp, "_recalc_receipt_totals", _noop())
    with pytest.raises(HTTPException) as e:
        run(cp.add_line("RC1", Req({"sku_code": "NGAWUR-01", "product_name": "Kaos ketikan"})))
    assert "master" in e.value.detail and db.cmt_receipt_lines.docs == []
    resp = run(cp.add_line("RC1", Req({"fg_material_id": "FG1", "qty_expected": 5})))
    line = json.loads(resp.body)
    assert (line["sku_code"], line["product_name"], line["manual"]) == ("SKU-1", "Kaos M", True)
    n = len(db.rahaza_materials.docs)
    assert run(cp._ensure_fg_for_cmt_line(db, {"sku_code": "BARU-9", "manual": True}, {}, WH)) is None
    assert len(db.rahaza_materials.docs) == n                        # tidak ada master lahir dari ketikan
    fg = run(cp._ensure_fg_for_cmt_line(db, {"sku_code": "PO-SKU", "po_item_id": "pi1"}, {"receipt_code": "R"}, WH))
    assert fg and fg["code"] == "PO-SKU"                             # baris dari PO: jalur lama tetap


# ═════════════════════ PRODUKSI 4 · laporan variance: qty sistem & nilai GL ═════════════════════
def _var_env(monkeypatch, db):
    import routes.exceptions as ex

    async def auth(_r):
        return {**WH, "role": "admin"}

    async def none(*a, **k):
        return None

    async def vid(*a, **k):
        return "V1"
    monkeypatch.setattr(ex, "require_auth", auth)
    monkeypatch.setattr(ex, "get_db", lambda: db)
    monkeypatch.setattr(ex, "deny_klien", lambda u: None)
    monkeypatch.setattr(ex, "require_write_actor", lambda u, f: None)
    monkeypatch.setattr(ex, "resolve_override", none)
    monkeypatch.setattr(ex, "effective_vendor_id", vid)
    monkeypatch.setattr(ex, "ov_stamp", lambda o: {})
    monkeypatch.setattr(ex, "log_activity", _noop())
    monkeypatch.setattr(ex, "check_role", lambda u, r, *a: True)
    return ex


def test_variance_qty_dari_sistem_dan_nilai_gl_wac(monkeypatch):
    from core import fg_cost_layers as fcl
    db = DB()
    db.production_jobs.docs.append({"id": "J1", "vendor_id": "V1", "vendor_name": "CMT A", "po_id": "PO1",
                                    "job_number": "JOB-1", "business_type": "internal"})
    db.production_job_items.docs += [
        {"id": "JI1", "job_id": "J1", "ordered_qty": 10, "produced_qty": 12, "sku": "SKU-1", "product_name": "Kaos"},
        {"id": "JI2", "job_id": "J1", "ordered_qty": 5, "produced_qty": 5, "sku": "SKU-2"}]
    db.rahaza_materials.docs.append({"id": "FG1", "type": "fg", "code": "SKU-1"})
    ex = _var_env(monkeypatch, db)
    resp = run(ex.create_variance(Req({"job_id": "J1", "variance_type": "OVERPRODUCTION",
                                       "items": [{"job_item_id": "JI1", "variance_qty": 99}]})))
    v = json.loads(resp.body)
    assert v["items"][0]["variance_qty"] == 2 and v["total_variance_qty"] == 2 and v["qty_source"] == "system"
    with pytest.raises(HTTPException):                               # tidak ada baris yang kurang
        run(ex.create_variance(Req({"job_id": "J1", "variance_type": "UNDERPRODUCTION"})))
    posted = []

    async def wac(db_, mid, **kw):
        return {"unit_cost": 25000.0}

    async def post(db_, var, user):
        posted.append(var["variance_value"])
        return {"ok": True, "je_id": "j1", "je_number": "JE-1"}
    monkeypatch.setattr(fcl, "wac_state", wac)
    monkeypatch.setattr(rp, "post_production_variance", post)
    # Tahap 9 (7 Nov 2026): jurnal OVER/UNDER dipensiunkan — nilai buku tidak boleh berbeda dari stok.
    # Endpoint lama tetap ada (tautan lama) dan menjawab 410 tanpa memposting apa pun.
    for fn in (ex.post_variance_to_gl, ex.retry_variance_posting):
        with pytest.raises(HTTPException) as e:
            run(fn(v["id"], Req({"unit_cost": 1})))
        assert e.value.status_code == 410 and "stok" in e.value.detail
    assert posted == []
    with pytest.raises(HTTPException) as e:
        run(ex.post_variance_to_gl("tidak-ada", Req()))
    assert e.value.status_code == 404


# ═════════════════════ MIGRASI · SJ internal lama ═════════════════════
def _load_migration():
    path = os.path.join(BACKEND, "scripts", "migrations", "2026_11_06_sj_internal.py")
    spec = importlib.util.spec_from_file_location("mig_sj_internal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_sj_internal_pratinjau_tandai_idempoten():
    mod = _load_migration()
    db = DB()
    db.wh_delivery_notes.docs += [
        {"id": "a", "sj_number": "SJ-A", "sj_type": "SJ-INTERNAL", "status": "issued", "lines": [{}, {}]},
        {"id": "b", "sj_number": "SJ-B", "sj_type": "SJ-INTERNAL", "status": "received", "lines": [{}]},
        {"id": "c", "sj_number": "SJ-C", "sj_type": "SJ-INTERNAL", "status": "issued", "stock_out_at": "x", "lines": [{}]},
        {"id": "d", "sj_number": "SJ-D", "sj_type": "SJ-INTERNAL", "status": "draft", "lines": []},
        {"id": "e", "sj_number": "SJ-E", "sj_type": "SJ-CMT", "status": "issued", "lines": [{}]}]
    db.wh_pending_movements.docs += [
        {"id": "p1", "type": "outbound_rm", "source_type": "delivery_note", "status": "pending"},
        {"id": "p2", "type": "outbound_rm", "source_type": "material_issue", "status": "pending"}]
    out = run(mod.migrate(db, False))
    assert (out["legacy_issued"], out["legacy_received"], out["legacy_lines"]) == (1, 1, 3)
    assert out["legacy_numbers"] == ["SJ-A", "SJ-B"] and out["drafts_without_location"] == 1
    assert out["orphan_pending"] == 1
    assert not any(d.get("stock_legacy") for d in db.wh_delivery_notes.docs)  # pratinjau tidak menulis
    run(mod.migrate(db, True))
    assert [d["id"] for d in db.wh_delivery_notes.docs if d.get("stock_legacy")] == ["a", "b"]
    assert db.wh_pending_movements.docs[0]["status"] == "cancelled"
    assert db.wh_pending_movements.docs[1]["status"] == "pending"
    again = run(mod.migrate(db, True))
    assert (again["legacy_issued"], again["legacy_received"], again["orphan_pending"]) == (0, 0, 0)


def test_lokasi_dalam_perjalanan_dikecualikan_dari_rekonsiliasi():
    from core import location_resolver as lr
    db = DB()
    tid = run(stock_transfer.transit_location_id(db))
    assert run(stock_transfer.transit_location_id(db)) == tid        # dibuat sekali
    idx = run(lr.storage_location_index(db))
    assert lr.classify_location(idx, tid) == lr.KIND_EXEMPT           # tidak dipindah otomatis
    assert tid in run(stock_transfer.blocked_ids(db))
