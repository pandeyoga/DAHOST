"""Uji unit HERMETIK Tahap 1 Gudang + Pengadaan (2026-11-06) — cacat jelas yang disetujui owner.

Angka harapan DIHITUNG TANGAN:
  * Klik ganda / dua pengguna: GR 10 pcs @1.000 → stok +10 SEKALI, jurnal Dr 1-1402 / Cr 2-1150 10.000 SEKALI.
  * Opname 100 → dihitung 98 (selisih −2 × 10.000 = −20.000). Transaksi lain keluar 5 di sela baca & tulis:
    stok akhir 100 − 5 − 2 = 93 (cara lama: set absolut 98 → 5 yang keluar terhapus).
  * Retur Material 20 @HPP keluar 55.000 ke stok 100 @60.000: HPP baru (100 × 60.000 + 20 × 55.000) / 120
    = 7.100.000 / 120 = 59.166,6667; jurnal Dr 1-1401 / Cr akun yang didebit MI asal 1.100.000.
  * PO dua baris material sama (10 + 5): GR tertaut baris ke-2 qty 5 → baris 1 tetap 0, baris 2 = 5.
    GR lama tanpa tautan qty 12 → baris 1 = 10, baris 2 = 2.
  * Retur Pembelian: baris GR diterima 100 → retur 60 lalu 50 = 110 > 100 → ditolak (sisa 40).
  * Tagihan dari GR 10 @1.000: tagih sebagian 4 → sisa 6 (6.000) tetap bisa ditagih; 7 > sisa 6 ditolak.
  * Jatuh tempo: faktur 2026-11-06 + PO NET 30 = 2026-12-06; pemasok net14 = 2026-11-20.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_tahap1_gudang_pengadaan.py -q
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
from core import purchase_returns as pr  # noqa: E402
from core import quarantine as qmod  # noqa: E402
from core import stock_service  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}
FIN = {"id": "u-fin", "name": "Keuangan Uji", "email": "fin@x", "role": "accounting"}
SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}


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

    async def body(self):
        return b"{}" if self._b else b""


# ── Mongo palsu: + find_one_and_update / array_filters / upsert (milik berkas ini) ──
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
        return fm._Result()

    async def find_one_and_update(self, q, upd, **kw):
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
def posting(monkeypatch):
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "source_module": mod,
              "source_ref": ref, "lines": [dict(ln) for ln in lines]}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(pp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def lines(i=-1):
        return sorted((ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in jes[i]["lines"])
    return types.SimpleNamespace(jes=jes, lines=lines)


def _noop_factory():
    async def noop(*a, **k):
        return None
    return noop


# ══════════════════════════════ 1a. GR: klaim atomik ══════════════════════════════
def _gr_env(monkeypatch, db, user=WH):
    import routes.warehouse as wh
    st = types.SimpleNamespace(adds=[], on_add=None)

    async def auth(_r):
        return user

    async def add(mid, loc, qty, **kw):
        st.adds.append((mid, loc, qty))
        if st.on_add:
            hook, st.on_add = st.on_add, None
            await hook()
        return {}

    async def vonhand(db_, mid):
        return 0.0

    async def qinfo(db_):
        return {"id": "LOC-Q", "code": "ZNA-KARANTINA", "name": "Karantina"}

    async def qin(db_, **kw):
        return {"id": "qi-new"}

    async def apply_cost(db_, mid, q, cost, **kw):
        return {"old_unit_cost": 0.0, "new_unit_cost": cost}
    monkeypatch.setattr(wh, "require_auth", auth)
    monkeypatch.setattr(wh, "get_db", lambda: db)
    monkeypatch.setattr(wh, "log_activity", _noop_factory())
    monkeypatch.setattr(wh.stock_service, "add", add)
    monkeypatch.setattr(wh.quarantine, "valued_onhand", vonhand)
    monkeypatch.setattr(wh.quarantine, "quarantine_in", qin)
    monkeypatch.setattr(wh.quarantine, "get_quarantine_location_info", qinfo)
    monkeypatch.setattr(wh.accessory_valuation, "apply_receipt_cost", apply_cost)
    return wh, st


def _gr_db(items=None, **gr):
    db = DB()
    db.rahaza_materials.docs.append({"id": "A", "code": "A-KCG", "name": "Kancing", "type": "accessory",
                                     "unit": "pcs", "unit_cost": 1000.0})
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-00001", "status": "draft", "location_id": "GD-L1",
        "supplier_name": "PT Uji",
        "items": items if items is not None else [{"id": "L1", "material_id": "A", "sku": "A-KCG",
                                                   "received_qty": 10, "rejected_qty": 0, "unit": "pcs",
                                                   "unit_price": 1000.0}], **gr})
    return db


def test_gr_konfirmasi_dua_kali_stok_dan_jurnal_sekali(monkeypatch, posting):
    db = _gr_db()
    wh, st = _gr_env(monkeypatch, db)
    second = {}

    async def concurrent():                    # pengguna kedua menekan konfirmasi di tengah proses pertama
        try:
            await wh.update_receiving("GR1", Req({"status": "received"}))
        except HTTPException as e:
            second["err"] = e
    st.on_add = concurrent
    out = run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert out["status"] == "received"
    assert second["err"].status_code == 409 and "sedang dikonfirmasi" in second["err"].detail
    with pytest.raises(HTTPException) as e:    # klik ganda sesudah selesai
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 409 and "sudah dikonfirmasi" in e.value.detail
    assert st.adds == [("A", "GD-L1", 10.0)]
    assert len(posting.jes) == 1 and posting.lines() == [("1-1402", 10000.0, 0), ("2-1150", 0, 10000.0)]


def test_gr_gagal_di_tengah_klaim_dilepas_lalu_bisa_ulang(monkeypatch, posting):
    db = _gr_db()
    wh, st = _gr_env(monkeypatch, db)

    async def boom():
        raise RuntimeError("koneksi putus")
    st.on_add = boom
    with pytest.raises(RuntimeError):
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert db.warehouse_receiving.docs[0]["status"] == "draft"          # klaim dilepas
    out = run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert out["status"] == "received"
    # GR yang sedang diklaim tidak bisa diubah/dihapus
    db.warehouse_receiving.docs.append({"id": "GR2", "receipt_number": "GR-2", "status": "processing", "items": []})
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("GR2", Req({"notes": "x"})))
    assert e.value.status_code == 409


# ══════════════════════ 8 · 9 · 13. validasi konfirmasi GR ═════════════════════════
def test_gr_po_dibatalkan_ditolak(monkeypatch, posting):
    db = _gr_db(po_id="PO1", po_number="PO-1")
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "cancelled",
                                           "items": [{"id": "pi1", "material_id": "A", "qty_ordered": 10}]})
    wh, st = _gr_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "sudah dibatalkan" in e.value.detail
    assert db.warehouse_receiving.docs[0]["status"] == "draft" and st.adds == [] and posting.jes == []


def test_gr_ditolak_melebihi_diterima_dan_accepted_dihitung_ulang(monkeypatch, posting):
    db = _gr_db(items=[{"id": "L1", "material_id": "A", "sku": "A-KCG", "received_qty": 5, "rejected_qty": 7,
                        "unit": "pcs", "unit_price": 1000.0}])
    wh, st = _gr_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "ditolak 7 > diterima 5" in e.value.detail
    item = {"id": "L1", "material_id": "A", "sku": "A-KCG", "received_qty": 10, "rejected_qty": 2,
            "accepted_qty": 50, "unit": "pcs", "unit_price": 1000.0}     # accepted lama/basi
    out = run(wh.update_receiving("GR1", Req({"status": "received", "items": [item]})))
    assert out["items"][0]["accepted_qty"] == 8.0 and st.adds == [("A", "GD-L1", 8.0)]


def test_gr_baris_tanpa_master_item_ditolak_aset_dikecualikan(monkeypatch, posting):
    db = _gr_db(items=[
        {"id": "L1", "material_id": "A", "sku": "A-KCG", "received_qty": 10, "unit_price": 1000.0},
        {"id": "L2", "material_id": None, "product_name": "Kardus polos", "received_qty": 3, "unit_price": 500.0},
        {"id": "L3", "material_id": None, "product_name": "Baris kosong", "received_qty": 0}])
    wh, st = _gr_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "Kardus polos" in e.value.detail and "Baris kosong" not in e.value.detail
    assert db.warehouse_receiving.docs[0]["status"] == "draft" and st.adds == []
    # baris aset tetap (item_type='asset') dikapitalisasi lewat registri aset → tidak diblokir
    db.warehouse_receiving.docs[0]["items"][1]["item_type"] = "asset"

    async def cap(*a, **k):
        return []
    monkeypatch.setattr(wh, "_capitalize_assets_from_grn", cap)
    assert run(wh.update_receiving("GR1", Req({"status": "received"})))["status"] == "received"


def test_gr_lewat_sisa_baris_po_per_po_item_id(monkeypatch, posting):
    db = _gr_db(po_id="PO1", po_number="PO-1",
                items=[{"id": "L1", "material_id": "A", "sku": "A-KCG", "po_item_id": "pi2", "received_qty": 6}])
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "approved", "items": [
        {"id": "pi1", "material_id": "A", "qty_ordered": 10, "qty_received": 0, "unit_cost": 1000.0},
        {"id": "pi2", "material_id": "A", "qty_ordered": 5, "qty_received": 0, "unit_cost": 1000.0}]})
    wh, st = _gr_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:          # baris 2 dipesan 5; dulu lolos (sisa per material 15)
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "melebihi sisa PO 5" in e.value.detail


# ══════════════════════════ 6. qty diterima PO per baris ══════════════════════════
def test_po_material_sama_dua_baris_diisi_per_baris():
    import routes.rahaza_po as rpo
    db = DB()
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "approved", "items": [
        {"id": "pi1", "material_id": "A", "qty_ordered": 10, "qty_received": 0},
        {"id": "pi2", "material_id": "A", "qty_ordered": 5, "qty_received": 0}]})
    run(rpo.update_po_received_qty(db, "PO1", [{"material_id": "A", "po_item_id": "pi2", "qty": 5}]))
    items = db.rahaza_purchase_orders.docs[0]["items"]
    assert [i["qty_received"] for i in items] == [0, 5]            # dulu [5, 5]
    assert db.rahaza_purchase_orders.docs[0]["status"] == "partially_received"
    run(rpo.update_po_received_qty(db, "PO1", [{"material_id": "A", "po_item_id": "pi1", "qty": 10}]))
    assert [i["qty_received"] for i in db.rahaza_purchase_orders.docs[0]["items"]] == [10, 5]
    assert db.rahaza_purchase_orders.docs[0]["status"] == "fully_received"
    # GR lama tanpa tautan baris: dibagi berurutan sesuai sisa, lebihnya ke baris terakhir
    db.rahaza_purchase_orders.docs[0].update(status="approved", items=[
        {"id": "pi1", "material_id": "A", "qty_ordered": 10, "qty_received": 0},
        {"id": "pi2", "material_id": "A", "qty_ordered": 5, "qty_received": 0}])
    run(rpo.update_po_received_qty(db, "PO1", [{"material_id": "A", "qty": 12}]))
    assert [i["qty_received"] for i in db.rahaza_purchase_orders.docs[0]["items"]] == [10, 2]


# ══════════════════════════════ 11. nomor GR satu pencacah ════════════════════════
def test_nomor_gr_memakai_pencacah_kanonik(monkeypatch):
    import inspect
    import routes.warehouse as wh
    import routes.rahaza_po as rpo
    calls = []

    async def gen(db, coll, field, prefix, width=4, **kw):
        calls.append((coll, field, prefix, width))
        return f"{prefix}{len(calls):0{width}d}"
    db = DB()

    async def auth(_r):
        return WH
    monkeypatch.setattr(wh, "gen_prefixed_number", gen)
    monkeypatch.setattr(wh, "require_auth", auth)
    monkeypatch.setattr(wh, "get_db", lambda: db)
    monkeypatch.setattr(wh, "log_activity", _noop_factory())
    out = run(wh.create_receiving(Req({"items": [{"material_id": "A", "received_qty": 0}]})))
    assert out["receipt_number"] == "GR-00001"
    assert calls == [("warehouse_receiving", "receipt_number", "GR-", 5)]
    # jalur "Buat GR dari PO" memakai kunci pencacah yang SAMA
    assert '"warehouse_receiving", "receipt_number",' in inspect.getsource(rpo.create_gr_from_po)
    assert "next_counter" not in inspect.getsource(wh.create_receiving)
    with pytest.raises(HTTPException) as e:
        run(wh.create_receiving(Req({"items": [{"material_id": "A", "received_qty": 1, "rejected_qty": 2}]})))
    assert e.value.status_code == 400 and "tidak boleh melebihi" in e.value.detail


# ══════════════════════════ 1b. Pengeluaran Material (MI) ═════════════════════════
def _mi_env(monkeypatch, db, *, neg=True):
    from core import material_issue_engine as mie
    from core import negative_stock
    st = types.SimpleNamespace(issues=[], adds=[], on_issue=None, fail_mid=None, posts=[])

    async def issue(mid, loc, qty, **kw):
        if st.on_issue:
            hook, st.on_issue = st.on_issue, None
            await hook()
        if mid == st.fail_mid:
            raise stock_service.InsufficientStock(mid, loc, qty, 0)
        st.issues.append((mid, loc, qty))
        return {}

    async def add(mid, loc, qty, **kw):
        st.adds.append((mid, loc, qty))
        return {}

    async def allowed(db_):
        return neg

    async def post(db_, mi, user):
        st.posts.append(mi["id"])
        return {"ok": True, "je_number": f"JE-MI-{len(st.posts)}"}
    monkeypatch.setattr(stock_service, "issue", issue)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(negative_stock, "allowed", allowed)
    monkeypatch.setattr(rp, "post_inventory_issue", post)
    return mie, st


def _mi_db():
    db = DB()
    db.rahaza_materials.docs += [{"id": "K", "code": "KN-1", "type": "fabric", "unit": "kg", "unit_cost": 50000.0},
                                 {"id": "A", "code": "A-LBL", "type": "accessory", "unit": "pcs", "unit_cost": 1000.0}]
    db.rahaza_locations.docs.append({"id": "GD-L1", "code": "GD-L1", "name": "Gudang 1"})
    db.rahaza_material_stock.docs += [{"material_id": "K", "location_id": "GD-L1", "qty": 100},
                                      {"material_id": "A", "location_id": "GD-L1", "qty": 100}]
    db.rahaza_material_issues.docs.append({
        "id": "MI1", "mi_number": "MI-001", "status": "pending_approval", "items": [
            {"id": "i1", "material_id": "K", "qty_required": 10, "location_id": "GD-L1"},
            {"id": "i2", "material_id": "A", "qty_required": 20, "location_id": "GD-L1"}]})
    return db


def test_mi_dua_kali_stok_dan_jurnal_sekali(monkeypatch):
    db = _mi_db()
    mie, st = _mi_env(monkeypatch, db)
    second = {}

    async def concurrent():
        mi2 = await db.rahaza_material_issues.find_one({"id": "MI1"})
        try:
            await mie.issue_material_issue(db, {**mi2, "status": "pending_approval"}, SA)
        except mie.AlreadyProcessing as e:
            second["err"] = e
    st.on_issue = concurrent
    out = run(mie.issue_material_issue(db, copy.deepcopy(db.rahaza_material_issues.docs[0]), SA))
    assert out["status"] == "issued" and "sedang/sudah" in str(second["err"])
    with pytest.raises(mie.AlreadyProcessing):          # klik ganda sesudah selesai
        run(mie.issue_material_issue(db, copy.deepcopy(db.rahaza_material_issues.docs[0]), SA))
    assert st.issues == [("K", "GD-L1", 10.0), ("A", "GD-L1", 20.0)] and st.posts == ["MI1"]
    assert len([m for m in db.rahaza_material_movements.docs if m.get("ref_id") == "MI1"]) == 2


def test_mi_route_approve_ganda_409(monkeypatch):
    import routes.rahaza_inventory_issues as rii
    db = _mi_db()
    mie, st = _mi_env(monkeypatch, db)

    async def auth(_r):
        return SA
    monkeypatch.setattr(rii, "_require_mi_approver", auth)
    monkeypatch.setattr(rii, "get_db", lambda: db)
    monkeypatch.setattr(rii, "log_activity", _noop_factory())
    # penyetuju kedua membaca MI masih 'pending_approval', padahal penyetuju pertama sudah mengklaimnya
    coll = db.rahaza_material_issues
    stale = copy.deepcopy(coll.docs[0])
    coll.docs[0]["status"] = "issuing"
    real_find = coll.find_one

    async def stale_once(q=None, projection=None, **kw):
        coll.find_one = real_find
        return copy.deepcopy(stale)
    coll.find_one = stale_once
    with pytest.raises(HTTPException) as e:
        run(rii.approve_mi("MI1", Req()))
    assert e.value.status_code == 409 and st.issues == []
    coll.docs[0]["status"] = "pending_approval"
    assert run(rii.approve_mi("MI1", Req()))["status"] == "issued"
    assert st.issues == [("K", "GD-L1", 10.0), ("A", "GD-L1", 20.0)]


def test_mi_baris_kedua_kalah_balapan_semua_dikembalikan(monkeypatch):
    db = _mi_db()
    mie, st = _mi_env(monkeypatch, db, neg=False)
    st.fail_mid = "A"                                   # stok A diambil transaksi lain di sela cek & potong
    with pytest.raises(mie.MaterialShortage):
        run(mie.issue_material_issue(db, copy.deepcopy(db.rahaza_material_issues.docs[0]), SA))
    assert st.issues == [("K", "GD-L1", 10.0)] and st.adds == [("K", "GD-L1", 10.0)]   # K dikembalikan
    assert db.rahaza_material_issues.docs[0]["status"] == "pending_approval"           # klaim dilepas
    assert not db.rahaza_material_movements.docs and st.posts == []
    st.fail_mid = None
    assert run(mie.issue_material_issue(db, copy.deepcopy(db.rahaza_material_issues.docs[0]), SA))["status"] == "issued"


# ══════════════════════ 1c · 3 · 4. Retur Material (dari produksi) ═════════════════
def _pmr_env(monkeypatch, db, je_debit=None):
    import routes.production_material_returns as pmr
    from core import location_resolver
    st = types.SimpleNamespace(adds=[], issues=[], on_add=None, wac=[])

    async def auth(_r):
        return SA

    async def yes(db_, lid):
        return True

    async def add(mid, loc, qty, **kw):
        st.adds.append((mid, loc, qty))
        if st.on_add:
            hook, st.on_add = st.on_add, None
            await hook()
        return {}

    async def issue(mid, loc, qty, **kw):
        st.issues.append((mid, loc, qty))
        return {}

    async def existing_je(db_, mod, ref):
        if je_debit and mod == "inventory_issue" and ref in je_debit:
            return {"id": "je-mi", "je_number": "JE-MI", "lines": [
                {"account_code": je_debit[ref], "debit": 100.0, "credit": 0},
                {"account_code": "1-1401", "debit": 0, "credit": 100.0}]}
        return None
    monkeypatch.setattr(pmr, "require_auth", auth)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    monkeypatch.setattr(pmr, "log_activity", _noop_factory())
    monkeypatch.setattr(pmr.stock_service, "add", add)
    monkeypatch.setattr(pmr.stock_service, "issue", issue)
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    monkeypatch.setattr(rp, "_find_existing_je", existing_je)
    return pmr, st


def _pmr_db(mi_extra=None):
    db = DB()
    db.rahaza_materials.docs.append({"id": "K", "code": "KN-1", "type": "fabric", "unit": "kg", "unit_cost": 60000.0})
    db.rahaza_material_stock.docs.append({"material_id": "K", "location_id": "GD-L2", "qty": 100.0})
    db.rahaza_material_issues.docs.append({
        "id": "MI1", "mi_number": "MI-001", "status": "issued", **(mi_extra or {}),
        "items": [{"material_id": "K", "qty_issued": 120, "unit_cost_applied": 55000.0}]})
    db.production_material_returns.docs.append({
        "id": 7, "ref_no": "PMR/1", "status": "approved", "material_issue_id": "MI1", "mi_number": "MI-001",
        "items": [{"material_id": "K", "material_code": "KN-1", "qty_returned": 20, "condition": "good"}]})
    return db


def test_retur_material_dua_kali_stok_jurnal_sekali_dan_hpp_rata_rata(monkeypatch, posting):
    db = _pmr_db()
    pmr, st = _pmr_env(monkeypatch, db, je_debit={"mi:MI1": "1-1403"})
    second = {}

    async def concurrent():
        try:
            await pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2"))
        except HTTPException as e:
            second["err"] = e
    st.on_add = concurrent
    out = run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert out["posting"]["ok"] and second["err"].status_code == 409
    with pytest.raises(HTTPException) as e:
        run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert e.value.status_code == 409
    assert st.adds == [("K", "GD-L2", 20.0)]
    assert len(posting.jes) == 1 and posting.lines() == [("1-1401", 1100000.0, 0), ("1-1403", 0, 1100000.0)]
    mat = db.rahaza_materials.docs[0]
    assert mat["unit_cost"] == pytest.approx(59166.6667, abs=1e-3)     # (100 × 60.000 + 20 × 55.000) / 120
    assert "last_receipt_unit_cost" not in mat                          # retur bukan harga beli
    assert db.production_material_returns.docs[0]["status"] == "received"


def test_retur_material_mengkredit_akun_yang_didebit_mi_asal(monkeypatch, posting):
    db = _pmr_db()
    pmr, _ = _pmr_env(monkeypatch, db, je_debit={"mi:MI1": "1-1403-PRD"})   # profil berubah sesudah MI
    run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert ("1-1403-PRD", 0, 1100000.0) in posting.lines()


def test_retur_material_mi_cutting_tanpa_jurnal_wip_tidak_minus(monkeypatch, posting):
    db = _pmr_db(mi_extra={"source": "cutting", "ref_type": "cutting_issue", "stock_moved_by": "cutting"})
    db.rahaza_material_issues.docs[0]["items"][0].pop("unit_cost_applied")
    pmr, st = _pmr_env(monkeypatch, db)
    out = run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert st.adds == [("K", "GD-L2", 20.0)]                           # stok kembali
    assert posting.jes == [] and out["posting"]["skipped"] and "Cutting" in out["posting"]["reason"]
    assert db.rahaza_materials.docs[0]["unit_cost"] == 60000.0          # HPP tidak bergeser
    assert db.production_material_returns.docs[0]["gl_skip_reason"]


def test_retur_material_gagal_stok_dikembalikan_klaim_dilepas(monkeypatch, posting):
    db = _pmr_db()
    pmr, st = _pmr_env(monkeypatch, db)

    async def boom(*a, **k):
        raise RuntimeError("gagal menulis movement")
    monkeypatch.setattr(db.rahaza_material_movements, "insert_one", boom)
    with pytest.raises(RuntimeError):
        run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert st.adds == [("K", "GD-L2", 20.0)] and st.issues == [("K", "GD-L2", 20.0)]
    assert db.production_material_returns.docs[0]["status"] == "approved"


# ══════════════════════ 1d. Karantina QC: keputusan ganda ════════════════════════
def _wq_db():
    db = DB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN-X", "name": "Kain", "type": "fabric",
                                     "unit": "kg", "unit_cost": 50000.0})
    db.wh_quarantine_items.docs.append({
        "id": "q1", "material_id": "X", "material_code": "KN-X", "unit": "kg", "unit_cost": 50000.0,
        "qty": 10, "remaining_qty": 10, "valued_qty": 10, "status": "open", "location_id": "LOC-Q",
        "source": {"type": "manual"}, "dispositions": []})
    return db


def _wq_env(monkeypatch, db):
    import routes.wms_quarantine as wq
    from core import location_resolver
    st = types.SimpleNamespace(ops=[], on_move=None)

    async def auth(_r):
        return WH

    async def yes(db_, lid):
        return True

    def rec(op):
        async def f(*a, **k):
            if op in ("move", "issue") and st.on_move:
                hook, st.on_move = st.on_move, None
                await hook()
            st.ops.append((op, a[:4]))
            return {}
        return f
    for op in ("add", "issue", "move", "release"):
        monkeypatch.setattr(stock_service, op, rec(op))

    async def qloc(db_):
        return "LOC-Q"
    monkeypatch.setattr(qmod, "get_quarantine_location_id", qloc)
    monkeypatch.setattr(wq, "require_auth", auth)
    monkeypatch.setattr(wq, "get_db", lambda: db)
    monkeypatch.setattr(wq, "log_activity", _noop_factory())
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    return wq, st


def test_karantina_scrap_ganda_stok_dan_jurnal_sekali(monkeypatch, posting):
    db = _wq_db()
    wq, st = _wq_env(monkeypatch, db)
    second = {}

    async def concurrent():
        try:
            await wq.scrap_item("q1", Req({"qty": 10}))
        except HTTPException as e:
            second["err"] = e
    st.on_move = concurrent
    out = run(wq.scrap_item("q1", Req({"qty": 10})))
    assert out["closed"] is True and second["err"].status_code == 409
    assert [o for o in st.ops if o[0] == "issue"] == [("issue", ("X", "LOC-Q", 10.0))]
    assert len(posting.jes) == 1 and posting.lines() == [("1-1401", 0, 500000.0), ("6-4300", 500000.0, 0)]
    q = db.wh_quarantine_items.docs[0]
    assert q["disposition_lock"] is None and q["valued_qty"] == 0
    with pytest.raises(HTTPException) as e:               # klik ganda sesudah selesai
        run(wq.scrap_item("q1", Req({"qty": 10})))
    assert e.value.status_code == 400


def test_karantina_lepas_ganda_kedua_409_lalu_kunci_dilepas(monkeypatch, posting):
    db = _wq_db()
    wq, st = _wq_env(monkeypatch, db)
    second = {}

    async def concurrent():
        try:
            await wq.release_item("q1", Req({"qty": 4, "to_location_id": "GD-L2"}))
        except HTTPException as e:
            second["err"] = e
    st.on_move = concurrent
    out = run(wq.release_item("q1", Req({"qty": 4, "to_location_id": "GD-L2"})))
    assert out["remaining_qty"] == 6 and second["err"].status_code == 409
    assert [o for o in st.ops if o[0] == "move"] == [("move", ("X", "LOC-Q", "GD-L2", 4.0))]
    # kunci dilepas → disposisi berikutnya jalan; kunci basi (≥ 10 menit) boleh diambil alih
    run(wq.release_item("q1", Req({"qty": 2, "to_location_id": "GD-L2"})))
    q = db.wh_quarantine_items.docs[0]
    q.update(disposition_lock="lama", disposition_lock_at=datetime.now(timezone.utc) - timedelta(minutes=11))
    assert run(wq.release_item("q1", Req({"qty": 1, "to_location_id": "GD-L2"})))["remaining_qty"] == 3
    q.update(disposition_lock="lain", disposition_lock_at=datetime.now(timezone.utc))
    with pytest.raises(HTTPException) as e:
        run(wq.release_item("q1", Req({"qty": 1, "to_location_id": "GD-L2"})))
    assert e.value.status_code == 409 and q["remaining_qty"] == 3


# ══════════════════════════════════ 2. Opname ══════════════════════════════════
T0 = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def opn(monkeypatch, posting):
    from core import opname_engine as eng
    db = DB()
    db.rahaza_locations.docs.append({"id": "L2", "code": "GD-L2", "name": "Gudang L2", "storage_role": "bahan"})
    db.rahaza_materials.docs.append({"id": "K", "code": "KN-1", "name": "Kain", "type": "fabric", "unit": "kg",
                                     "unit_cost": 10000.0})
    db[stock_service.STOCK].docs.append({"id": "s1", "material_id": "K", "location_id": "L2", "qty": 100.0})
    db[eng.SESS].docs.append({
        "id": "S1", "session_no": "OPN-1", "engine": eng.ENGINE, "level": "lokasi", "status": "submitted",
        "location_id": "L2", "location_code": "GD-L2", "location_ids": ["L2"], "snapshot_at": T0,
        "count_date": "2026-11-02",
        "lines": [{"key": "K", "material_id": "K", "material_code": "KN-1", "kind": "bahan", "unit": "kg",
                   "snapshot_qty": 100.0, "unit_cost": 10000.0, "status": "belum", "reason": "", "bin_id": ""}]})
    db[eng.CNT].docs.append({"session_id": "S1", "material_id": "K", "bin_id": "", "counted_qty": 98.0,
                             "counted_at": T0 + timedelta(minutes=5)})

    async def adjust_by(material_id, location_id, delta, *, meta=None, ref=None, actor=None, db=None):
        row = next(r for r in db[stock_service.STOCK].docs
                   if r["material_id"] == material_id and r["location_id"] == location_id)
        row["qty"] = round(row["qty"] + delta, 4)          # $inc atomik
        return row

    async def forbidden(*a, **k):
        raise AssertionError("approve opname tidak boleh menimpa qty absolut")
    monkeypatch.setattr(stock_service, "adjust_by", adjust_by)
    monkeypatch.setattr(stock_service, "adjust", forbidden)

    def stock():
        return db[stock_service.STOCK].docs[0]["qty"]

    async def sess():
        return await eng.get_session(db, "S1")
    return types.SimpleNamespace(db=db, eng=eng, stock=stock, sess=sess, jes=posting.jes)


def test_opname_jurnal_gagal_stok_tetap_dan_bisa_disetujui_ulang(opn, monkeypatch):
    eng = opn.eng
    real = rp._create_posted_je

    async def closed(*a, **k):
        return {"ok": False, "error": "Periode 2026-11 sudah ditutup"}
    monkeypatch.setattr(rp, "_create_posted_je", closed)
    with pytest.raises(HTTPException) as e:
        run(eng.approve(opn.db, SA, run(opn.sess())))
    assert e.value.status_code == 400 and "ditutup" in e.value.detail and "Stok belum diubah" in e.value.detail
    s = run(opn.sess())
    assert opn.stock() == 100.0 and s["status"] == "submitted" and not s.get("applied_keys")
    assert not opn.db.rahaza_material_movements.docs
    monkeypatch.setattr(rp, "_create_posted_je", real)
    out = run(eng.approve(opn.db, SA, run(opn.sess())))
    assert out["status"] == "approved" and opn.stock() == 98.0 and len(opn.jes) == 1
    assert opn.db.rahaza_material_movements.docs[0]["gl_je_id"] == "je-1"


def test_opname_selisih_ditulis_sebagai_delta_mutasi_lain_tidak_terhapus(opn, monkeypatch):
    eng = opn.eng
    real = eng._post_session_je

    async def with_concurrent_issue(db, user, sess, valued, je_date):
        # transaksi lain mengeluarkan 5 SESUDAH approve membaca stok, SEBELUM stok ditulis
        opn.db[stock_service.STOCK].docs[0]["qty"] -= 5
        return await real(db, user, sess, valued, je_date)
    monkeypatch.setattr(eng, "_post_session_je", with_concurrent_issue)
    out = run(eng.approve(opn.db, SA, run(opn.sess())))
    assert out["status"] == "approved"
    assert opn.stock() == 93.0                     # 100 − 5 − 2; cara lama menimpa 98 (5 keluar hilang)
    assert out["result"]["writes"][0]["delta"] == -2.0


# ═══════════════════════════ 7. Retur Pembelian dibatasi ═══════════════════════════
def _rtp_env(monkeypatch, db):
    import routes.rahaza_purchase_returns as rpr

    async def auth(_r):
        return SA
    for f in ("_require_proc_wh", "_require_fin", "_require_view"):
        monkeypatch.setattr(rpr, f, auth)
    monkeypatch.setattr(rpr, "get_db", lambda: db)
    monkeypatch.setattr(rpr, "log_activity", _noop_factory())
    n = {"i": 0}

    async def gen(db_, coll, field, prefix, width=4, **kw):
        n["i"] += 1
        return f"{prefix}{n['i']:0{width}d}"
    monkeypatch.setattr(rpr, "gen_prefixed_number", gen)

    async def qloc(db_):
        return "LOC-Q"
    monkeypatch.setattr(qmod, "get_quarantine_location_id", qloc)
    return rpr


def test_retur_pembelian_tidak_melebihi_qty_baris_gr(monkeypatch):
    db = DB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN-X", "name": "Kain", "type": "fabric", "unit": "kg"})
    db.warehouse_receiving.docs.append({"id": "GR1", "receipt_number": "GR-00001", "status": "received",
                                        "supplier_name": "PT Uji", "items": [
                                            {"id": "L1", "material_id": "X", "material_name": "Kain",
                                             "received_qty": 100, "rejected_qty": 0, "unit_price": 50000.0}]})
    db.rahaza_material_stock.docs.append({"material_id": "X", "location_id": "GD-L2", "qty": 500,
                                          "reserved_quantity": 0})
    rpr = _rtp_env(monkeypatch, db)

    def body(q):
        return Req({"settlement": "debit_note", "reason": "cacat", "gr_id": "GR1",
                    "lines": [{"material_id": "X", "location_id": "GD-L2", "qty": q, "gr_item_id": "L1"}]})
    run(rpr.create_purchase_return(body(60)))
    with pytest.raises(HTTPException) as e:
        run(rpr.create_purchase_return(body(50)))
    assert e.value.status_code == 400 and "sisa yang bisa diretur 40" in e.value.detail
    assert run(rpr.create_purchase_return(body(40)))["total_qty"] == 40
    # retur batal & tukar barang yang penggantinya sudah datang tidak mengurangi sisa
    db[pr.RTP_COLL].docs[0]["status"] = "cancelled"
    db[pr.RTP_COLL].docs[1].update(settlement="exchange", status="settled")
    assert run(rpr.create_purchase_return(body(100)))["total_qty"] == 100
    with pytest.raises(HTTPException):
        run(rpr.create_purchase_return(body(1)))
    # satu dokumen dengan dua baris pada baris GR yang sama juga dijumlahkan
    db[pr.RTP_COLL].docs.clear()
    with pytest.raises(HTTPException):
        run(rpr.create_purchase_return(Req({"settlement": "debit_note", "reason": "x", "gr_id": "GR1", "lines": [
            {"material_id": "X", "location_id": "GD-L2", "qty": 70, "gr_item_id": "L1"},
            {"material_id": "X", "location_id": "GD-L2", "qty": 31, "gr_item_id": "L1"}]})))


# ═════════════════ 5 · 10 · 12. Tagihan pemasok dari GR ═════════════════════════════
def _ap_env(monkeypatch, db):
    import routes.rahaza_ap_from_gr as apg
    import routes.rahaza_finance as rf

    async def fin(_r):
        return FIN

    async def mapping(db_, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def num(db_):
        num.i += 1
        return f"AP-T-{num.i}"
    num.i = 0

    async def void(db_, iid, user, reason=""):
        return void.result
    void.result = {"ok": True, "voided": True}
    monkeypatch.setattr(apg, "_require_finance", fin)
    monkeypatch.setattr(apg, "_require_finance_view", fin)
    monkeypatch.setattr(apg, "get_db", lambda: db)
    monkeypatch.setattr(apg, "get_mapping", mapping)
    monkeypatch.setattr(apg, "log_activity", _noop_factory())
    monkeypatch.setattr(apg, "_gen_ap_number", num)
    monkeypatch.setattr(apg, "_today_iso", lambda: "2026-11-06")
    monkeypatch.setattr(rf, "_require_fin", fin)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "void_ap_invoice_posting", void)
    return apg, rf, void


def _ap_db(**gr):
    db = DB()
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-00001", "status": "received", "supplier_name": "PT Uji",
        "items": [{"id": "L1", "material_id": "X", "material_name": "Kain", "received_qty": 10, "rejected_qty": 0,
                   "unit_price": 1000.0}], **gr})
    return db


def _pay(**kw):
    import routes.rahaza_ap_from_gr as apg
    return apg.CreateAPFromGRPayload(gr_ids=["GR1"], **kw)


def test_tagihan_sebagian_sisa_tetap_bisa_ditagih_dan_qty_dibatasi(monkeypatch):
    db = _ap_db()
    apg, rf, _ = _ap_env(monkeypatch, db)
    ov = apg.CreateAPFromGRItem
    with pytest.raises(HTTPException) as e:
        run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=11)]), Req()))
    assert e.value.status_code == 400 and "melebihi qty yang belum ditagih" in e.value.detail and "Kain" in e.value.detail
    inv1 = run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=4)]), Req()))
    assert inv1["subtotal"] == 4000
    gr = db.warehouse_receiving.docs[0]
    line = gr["items"][0]
    assert line["base_billed_qty"] == 4 and line["base_ap_invoice_id"] is None and gr["has_unbilled_lines"] is True
    b = pr.gr_billable_lines(gr)
    assert [(x["qty"], x["amount"]) for x in b] == [(6, 6000)]
    with pytest.raises(HTTPException):
        run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=7)]), Req()))
    inv2 = run(apg.create_ap_invoice_from_gr(_pay(), Req()))           # sisanya
    assert inv2["subtotal"] == 6000 and inv2["gl_grni_amount"] == 6000
    line = db.warehouse_receiving.docs[0]["items"][0]
    assert line["base_billed_qty"] == 10 and line["base_ap_invoice_id"] == inv2["id"]
    assert db.warehouse_receiving.docs[0]["has_unbilled_lines"] is False
    with pytest.raises(HTTPException) as e:
        run(apg.create_ap_invoice_from_gr(_pay(), Req()))
    assert "sudah ditagih seluruhnya" in e.value.detail
    with pytest.raises(HTTPException) as e:                             # kunci baris tak dikenal
        run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="ZZ", invoiced_qty=1)]), Req()))
    assert e.value.status_code == 400


def test_batal_faktur_dari_gr_melepas_baris_gr(monkeypatch):
    db = _ap_db()
    apg, rf, void = _ap_env(monkeypatch, db)
    ov = apg.CreateAPFromGRItem
    inv1 = run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=4)]), Req()))
    inv2 = run(apg.create_ap_invoice_from_gr(_pay(), Req()))
    db.rahaza_ap_invoices.docs[0]["status"] = "sent"
    # jurnal tidak bisa dibalik (periode tertutup) → batal ditolak, GR tidak dilepas
    void.result = {"ok": False, "error": "Periode 2026-11 sudah ditutup"}
    with pytest.raises(HTTPException) as e:
        run(rf.change_ap_status(inv2["id"], Req({"status": "cancelled"})))
    assert e.value.status_code == 400 and "ditutup" in e.value.detail
    assert db.rahaza_ap_invoices.docs[1]["status"] == "draft" and not pr.gr_billable_lines(db.warehouse_receiving.docs[0])
    void.result = {"ok": True, "voided": True}
    out = run(rf.change_ap_status(inv2["id"], Req({"status": "cancelled"})))
    assert out["status"] == "cancelled" and out["_released_grs"] == ["GR-00001"]
    gr = db.warehouse_receiving.docs[0]
    assert [(x["qty"], x["amount"]) for x in pr.gr_billable_lines(gr)] == [(6, 6000)]
    assert gr["ap_invoice_id"] == inv1["id"] and gr["ap_invoice_ids"] == [inv1["id"]]
    assert gr["has_unbilled_lines"] is True
    with pytest.raises(HTTPException) as e:                              # batal dua kali
        run(rf.change_ap_status(inv2["id"], Req({"status": "cancelled"})))
    assert e.value.status_code == 400 and "sudah dibatalkan" in e.value.detail
    run(rf.change_ap_status(inv1["id"], Req({"status": "cancelled"})))
    gr = db.warehouse_receiving.docs[0]
    assert [(x["qty"], x["amount"]) for x in pr.gr_billable_lines(gr)] == [(10, 10000)]
    assert gr["ap_invoice_id"] is None
    inv3 = run(apg.create_ap_invoice_from_gr(_pay(), Req()))              # bisa ditagih ulang
    assert inv3["subtotal"] == 10000 and inv3["gl_grni_amount"] == 10000


def test_batal_faktur_gr_lama_tanpa_penanda_baris(monkeypatch):
    # GR lama (sebelum penanda per baris): hanya `ap_invoice_id` di dokumen
    db = _ap_db(ap_invoice_id="AP-OLD", ap_invoice_number="AP-OLD", ap_invoice_ids=["AP-OLD"])
    db.rahaza_ap_invoices.docs.append({"id": "AP-OLD", "invoice_number": "AP-OLD", "status": "sent", "source": "gr",
                                       "gr_ids": ["GR1"], "items": [{"gr_id": "GR1", "gr_item_id": "L1", "qty": 10,
                                                                     "amount": 10000, "gr_amount": 10000}]})
    apg, rf, _ = _ap_env(monkeypatch, db)
    assert not pr.gr_billable_lines(db.warehouse_receiving.docs[0])
    run(rf.change_ap_status("AP-OLD", Req({"status": "cancelled"})))
    assert [(x["qty"], x["amount"]) for x in pr.gr_billable_lines(db.warehouse_receiving.docs[0])] == [(10, 10000)]


def test_jatuh_tempo_mengikuti_termin_po_atau_pemasok(monkeypatch):
    db = _ap_db(po_id="PO1", po_number="PO-1")
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "payment_terms": "net30",
                                           "payment_term_days": 30})
    apg, rf, _ = _ap_env(monkeypatch, db)
    ov = apg.CreateAPFromGRItem
    inv = run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=1)]), Req()))
    assert (inv["issue_date"], inv["due_date"], inv["payment_terms"]) == ("2026-11-06", "2026-12-06", "net30")
    inv = run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=1)],
                                                 issue_date="2026-11-10"), Req()))
    assert inv["due_date"] == "2026-12-10"
    inv = run(apg.create_ap_invoice_from_gr(_pay(items_override=[ov(gr_item_id="L1", invoiced_qty=1)],
                                                 due_date="2026-11-30"), Req()))
    assert inv["due_date"] == "2026-11-30"                                # isian tetap menang
    # tanpa PO: termin master pemasok
    db2 = _ap_db(supplier_id="SUP1")
    db2.rahaza_suppliers.docs.append({"id": "SUP1", "payment_terms": "net14"})
    apg, rf, _ = _ap_env(monkeypatch, db2)
    assert run(apg.create_ap_invoice_from_gr(_pay(), Req()))["due_date"] == "2026-11-20"
    # tanpa data termin sama sekali: tanggal faktur (perilaku lama)
    db3 = _ap_db()
    apg, rf, _ = _ap_env(monkeypatch, db3)
    assert run(apg.create_ap_invoice_from_gr(_pay(), Req()))["due_date"] == "2026-11-06"
    assert apg._term_days_of("NET 45") == 45 and apg._term_days_of("cod") == 0 and apg._term_days_of("x") is None
