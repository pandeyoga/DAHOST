"""Uji HERMETIK skill Merchandiser (keputusan owner K-M1..K-M10, 12 Nov 2026).

Data sintetis kecil yang angkanya bisa dihitung tangan: model laris, lambat, mati, habis; pesanan batal & belum bayar
tidak dihitung; retur mengurangi; stok perkiraan = stok sistem − penjualan sejak saldo awal yang belum scan keluar;
penjualan tanpa model tercatat di cakupan. WIP (core.pantau_produksi) diganti tiruan.
Jalankan:  cd backend && python -m pytest tests/unit/test_merchandiser.py -n 0 -q
"""
import asyncio
import os
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ai_fakes  # noqa: E402,F401
import _fake_mongo as fm  # noqa: E402

from core import merchandiser as mc  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402

HARI = date(2026, 11, 12)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def T(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _order(oid, tgl, lines, status="completed", **kw):
    return {"order_id": oid, "account_id": "acc1", "status": status, "order_date": T(tgl), "items": lines, **kw}


def _ln(fg, model, qty, retur=0, sku="X"):
    return {"fg_material_id": fg, "model_id": model, "quantity": qty, "qty_returned": retur, "seller_sku": sku}


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    d.rahaza_models.docs = [{"id": "M1", "code": "DA-1", "name": "Laris", "hpp": 50000},
                            {"id": "M2", "code": "DA-2", "name": "Lambat", "hpp": 40000},
                            {"id": "M3", "code": "DA-3", "name": "Mati", "hpp": 30000},
                            {"id": "M4", "code": "DA-4", "name": "Habis", "hpp": 20000}]
    d.rahaza_materials.docs = [
        {"id": "fg1", "type": "fg", "model_id": "M1", "variant_id": "v1", "sku": "DA-1-HTM-S", "color_name": "Hitam",
         "size_code": "S", "wac_last": 52000},
        {"id": "fg1b", "type": "fg", "model_id": "M1", "variant_id": "v1b", "sku": "DA-1-PTH-M", "color_name": "Putih",
         "size_code": "M", "hpp": 50000},
        {"id": "fg2", "type": "fg", "model_id": "M2", "variant_id": "v2", "sku": "DA-2-ALL", "hpp": 40000},
        {"id": "fg3", "type": "fg", "model_id": "M3", "variant_id": "v3", "sku": "DA-3-ALL", "hpp": 30000},
        {"id": "fg4", "type": "fg", "model_id": "M4", "variant_id": "v4", "sku": "DA-4-ALL", "hpp": 20000}]
    d.rahaza_material_stock.docs = [
        {"material_id": "fg1", "inventory_category": "fg_internal", "qty": 40},
        {"material_id": "fg1b", "inventory_category": "fg_internal", "qty": 10},
        {"material_id": "fg2", "inventory_category": "fg_internal", "qty": 1000},
        {"material_id": "fg3", "inventory_category": "fg_internal", "qty": 50},
        {"material_id": "kain", "inventory_category": "raw_material", "qty": 999}]
    awal = {"type": "opening_stock", "source": "opening_stock"}
    d.rahaza_stock_ledger.docs = [
        {"material_id": m, "op": "add", "delta": q, "created_at": T("2026-11-10T11:00:00"), "ref": awal}
        for m, q in (("fg1", 40), ("fg1b", 10), ("fg2", 1000), ("fg3", 50))] + [
        {"material_id": "fg1", "op": "issue", "delta": -2, "created_at": T("2026-11-11T05:00:00"),
         "ref": {"type": "mp_scan_out"}},
        {"material_id": "fg2", "op": "issue", "delta": -5, "created_at": T("2026-11-11T05:00:00"),
         "ref": {"type": "transfer"}}]          # bukan penjualan → tidak mengurangi "belum tercatat"
    d.marketing_orders.docs = [
        _order("o1", "2026-10-20T03:00:00", [_ln("fg1", "M1", 190)]),
        _order("o2", "2026-11-11T03:00:00", [_ln("fg1", "M1", 10)]),
        _order("o3", "2026-10-25T03:00:00", [_ln("fg1b", "M1", 20, retur=2), _ln(None, None, 7, sku="3503")]),
        _order("o4", "2026-10-30T03:00:00", [_ln("fg2", "M2", 8)]),
        _order("o5", "2026-10-30T03:00:00", [_ln("fg2", "M2", 100)], status="cancelled"),
        _order("o6", "2026-10-30T03:00:00", [_ln("fg2", "M2", 50)], status="new"),            # belum dibayar
        _order("o7", "2026-10-01T03:00:00", [_ln("fg3", "M3", 5)]),                           # periode pembanding
        _order("o8", "2026-11-01T03:00:00", [_ln("fg4", "M4", 12)]),
        _order("o9", "2026-10-01T03:00:00", [_ln("fg1", "M1", 100)]),                         # periode pembanding
    ]
    d.marketing_platform_accounts.docs = [{"id": "acc1", "account_name": "Toko A"}]

    async def _wip(_db):
        return {"v1": 30}
    monkeypatch.setattr(mc, "wip_internal", _wip)

    async def _amb(_db):
        return mc.rapikan_ambang(None)
    monkeypatch.setattr(mc, "ambang", _amb)
    return d


def _per(rows):
    return {r["model_id"]: r for r in rows}


# ═══ fungsi murni ════════════════════════════════════════════════════════════
def test_kelas_dan_metrik():
    a = mc.rapikan_ambang(None)
    assert [mc.kelas_dari(laju, stok, wip, a) for laju, stok, wip in (
        (0, 0, 0), (0, 10, 0), (5, 0, 0), (10, 20, 0), (10, 50, 0), (10, 100, 0), (10, 200, 0))] == \
        ["kosong", "mati", "habis", "laris", "sehat", "awas", "lambat"]
    m = mc.metrik(40, 20, 100, 20, 4, a)
    assert m["laju_mingguan"] == 10 and m["minggu_persediaan"] == 12 and m["kelas"] == "awas" and m["tren"] == 2
    assert m["sell_through_persen"] == round(40 / 140 * 100, 1)
    assert mc.metrik(0, 0, 5, 0, 4, a)["minggu_persediaan"] == mc.BESAR
    assert mc.rapikan_ambang({"laris": 9, "sehat": 2})["laris"] == 3      # urutan tidak sah → bawaan
    assert mc.rapikan_ambang({"minggu_jual": 100})["minggu_jual"] == 26


# ═══ analisa ═════════════════════════════════════════════════════════════════
def test_analisa_per_model(db):
    out = run(mc.analisa(db, hari_ini=HARI))
    assert out["periode"] == {"dari": "2026-10-16", "sampai": "2026-11-12", "minggu": 4,
                              "pembanding": {"dari": "2026-09-18", "sampai": "2026-10-15"}}
    r = _per(out["baris"])
    # M1: terjual 190+10+(20−2)=218 → laju 54,5; stok fg1 40 − (10 terjual sejak saldo awal − 2 scan keluar) = 32,
    # fg1b 10 → 42; WIP 30 → (42+30)/54,5 = 1,3 minggu → laris
    assert r["M1"]["terjual"] == 218 and r["M1"]["laju_mingguan"] == 54.5 and r["M1"]["stok_perkiraan"] == 42
    assert r["M1"]["stok_sistem"] == 50 and r["M1"]["wip"] == 30 and r["M1"]["kelas"] == "laris"
    assert r["M1"]["minggu_persediaan"] == 1.3 and r["M1"]["terjual_sebelumnya"] == 100 and r["M1"]["tren"] == 2.18
    assert r["M1"]["nilai_stok_hpp"] == 32 * 52000 + 10 * 50000
    assert r["M1"]["toko_terlaris"] == [{"toko": "Toko A", "pcs": 218}]
    # M2: batal & belum bayar tidak dihitung → 8 pcs; transfer bukan penjualan → stok tetap 1000 → 500 minggu
    assert r["M2"]["terjual"] == 8 and r["M2"]["stok_perkiraan"] == 1000 and r["M2"]["kelas"] == "lambat"
    assert r["M2"]["minggu_persediaan"] == 500
    assert r["M3"]["kelas"] == "mati" and r["M3"]["terjual_sebelumnya"] == 5 and r["M3"]["minggu_persediaan"] == 999
    assert r["M4"]["kelas"] == "habis" and r["M4"]["stok_perkiraan"] == 0
    # urutan risiko: mati, lambat, awas, laris, habis, sehat
    assert [x["kelas"] for x in out["baris"]] == ["mati", "lambat", "laris", "habis"]
    assert out["ringkasan"]["lambat"]["stok"] == 1000 and out["ringkasan"]["mati"]["baris"] == 1
    c = out["cakupan"]
    assert c["pcs_tanpa_model"] == 7 and c["sku_tanpa_model"] == [{"sku": "3503", "pcs": 7}]
    assert c["penjualan_belum_scan_keluar_pcs"] == 8 and c["stok_sistem_pcs"] == 1100
    assert any("Jembatan SKU" in t for t in c["catatan"]) and any("PERKIRAAN" in t for t in c["catatan"])
    assert "Penjualan:" in out["sumber"]


def test_analisa_per_warna_varian_dan_toko(db):
    w = run(mc.analisa(db, hari_ini=HARI, tingkat="warna", model_id="M1"))["baris"]
    assert sorted((x["warna"], x["terjual"], x["stok_perkiraan"]) for x in w) == [("Hitam", 200, 32), ("Putih", 18, 10)]
    v = run(mc.analisa(db, hari_ini=HARI, tingkat="varian", model_id="M1"))["baris"]
    hitam = next(x for x in v if x["sku"] == "DA-1-HTM-S")
    assert hitam["ukuran"] == "S" and hitam["wip"] == 30
    kosong = run(mc.analisa(db, hari_ini=HARI, toko="toko-lain"))
    assert {x["model_id"]: x["terjual"] for x in kosong["baris"]}.get("M1") == 0


def test_cek_rencana(db):
    lambat = run(mc.cek_rencana(db, hari_ini=HARI, model_id="M2", qty=100))
    assert lambat["keputusan"] == "perlu_alasan" and "lambat" in lambat["alasan"][0]
    assert lambat["sesudah"]["wip"] == 100 and lambat["sekarang"]["kelas"] == "lambat"
    laris = run(mc.cek_rencana(db, hari_ini=HARI, model_id="M1", qty=50))
    assert laris["keputusan"] == "aman" and laris["sesudah"]["minggu_persediaan"] == round(122 / 54.5, 1)
    banyak = run(mc.cek_rencana(db, hari_ini=HARI, model_id="M1", qty=2000))
    assert banyak["keputusan"] == "perlu_alasan" and "batas" in banyak["alasan"][0]
    var = run(mc.cek_rencana(db, hari_ini=HARI, model_id="M1", qty=10, variant_id="v1b"))
    assert var["sekarang"]["terjual"] == 18


# ═══ pintu API & alat Asisten ════════════════════════════════════════════════
def test_route_dan_saringan_kelas(db, monkeypatch):
    from routes import merchandiser as rt
    user = {"id": "u1", "role": "owner"}

    async def _auth(_r):
        return dict(user)
    monkeypatch.setattr(rt, "require_auth", _auth)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "today_wib", lambda: HARI)
    out = run(rt.get_analisa(SimpleNamespace(), tingkat="model", minggu=None, toko=None, model_id=None,
                             kelas="mati,lambat"))
    assert {r["kelas"] for r in out["baris"]} == {"mati", "lambat"}
    with pytest.raises(HTTPException) as e:
        run(rt.get_analisa(SimpleNamespace(), tingkat="model", minggu=None, toko=None, model_id=None, kelas="aneh"))
    assert e.value.status_code == 400
    assert run(rt.get_cek_rencana(SimpleNamespace(), model_id="M2", qty=10, variant_id=None))["keputusan"] == \
        "perlu_alasan"
    user["role"] = "cmt_vendor"
    with pytest.raises(HTTPException) as e:
        run(rt.get_analisa(SimpleNamespace(), tingkat="model", minggu=None, toko=None, model_id=None, kelas=None))
    assert e.value.status_code == 403


class _Ctx:
    def __init__(self):
        self.calls = []
        self.pemanggil = "langsung"

    async def api(self, method, path, params=None, **kw):
        self.calls.append((method, path, dict(params or {})))
        return {"baris": [{"model_id": f"M{i}"} for i in range(60)], "cakupan": {}}


def test_alat_asisten():
    ab.muat_semua_alat()
    a = ab._DAFTAR["analisa_merchandiser"]
    ctx = _Ctx()
    out = run(a.handler(ctx, {"tingkat": "warna", "minggu": 8, "toko_id": "acc1", "kelas": ["mati", "lambat"]}))
    assert ctx.calls[0] == ("GET", "/api/merchandiser/analisa",
                            {"tingkat": "warna", "minggu": 8, "toko": "acc1", "kelas": "mati,lambat"})
    assert len(out["hasil"]["baris"]) == 40 and "60 baris" in out["hasil"]["catatan_baris"]
    c = ab._DAFTAR["cek_rencana_produksi"]
    ctx = _Ctx()
    run(c.handler(ctx, {"model_id": "M2", "qty": 100}))
    assert ctx.calls[0] == ("GET", "/api/merchandiser/cek-rencana", {"model_id": "M2", "qty": 100})
    assert a.domain == "stok" and c.domain == "produksi" and not a.adalah_tindakan
