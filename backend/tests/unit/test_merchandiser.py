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


# ═══ M2 — pengaman PO produksi & pembelian bahan (K-M2) ═══════════════════════
ALASAN = "Pesanan khusus toko offline sudah dibayar"


class _Req:
    def __init__(self, body):
        self._body = body
        self.state = SimpleNamespace()
        self.headers = {}

    async def json(self):
        return self._body


def _bom(db):
    db.rahaza_boms.docs = [
        {"model_id": "M2", "is_active": True, "materials": [{"material_id": "kain-lambat"}, {"material_id": "kain-umum"}]},
        {"model_id": "M3", "materials": [{"material_id": "kain-lambat"}]},
        {"model_id": "M1", "materials": [{"material_id": "kain-umum"}]},
        {"model_id": "M2", "is_active": False, "materials": [{"material_id": "kain-lama"}]},   # BOM nonaktif
        {"model_id": "M9", "materials": [{"material_id": "kain-baru"}]}]                      # model baru (kosong)
    db.rahaza_materials.docs += [{"id": "kain-lambat", "code": "K-01", "name": "Kain Lambat"}]


def test_keputusan_model_baru_dan_lama():
    a = mc.rapikan_ambang(None)
    baru = mc.keputusan(0, 0, 0, 0, 300, 4, a)
    assert baru["keputusan"] == "aman" and baru["baru"] is True       # peluncuran model baru tidak ditahan
    pernah = mc.keputusan(0, 12, 0, 0, 300, 4, a)                     # pernah laku, 4 minggu terakhir 0
    assert pernah["keputusan"] == "perlu_alasan" and "tak terbatas" in pernah["alasan"][0]
    assert mc.keputusan(40, 0, 20, 0, 10, 4, a)["keputusan"] == "aman"


def test_periksa_produksi_dan_wajib_alasan(db):
    db.rahaza_model_variants.docs = [{"id": "rv2", "model_id": "M2", "sku": "DA-2-ALL"}]
    per = run(mc.model_dari_item(db, [{"rahaza_variant_id": "rv2", "qty": 60}, {"model_id": "M2", "qty": 40},
                                      {"model_id": "M1", "qty": 20}, {"model_id": "M3", "qty": 0}]))
    assert per == {"M2": 100, "M1": 20}
    t = run(mc.periksa_produksi(db, per, hari_ini=HARI))
    assert [x["model_id"] for x in t] == ["M2"] and t[0]["kode"] == "DA-2" and t[0]["kelas"] == "lambat"
    with pytest.raises(HTTPException) as e:
        run(mc.jaga(db, langkah="po_produksi", alasan="", user={}, hari_ini=HARI, per_model=per))
    assert e.value.status_code == 428 and "DA-2" in e.value.detail and "PO produksi" in e.value.detail
    with pytest.raises(HTTPException):
        run(mc.jaga(db, langkah="po_produksi", alasan="promo", user={}, hari_ini=HARI, per_model=per))
    temuan, alasan = run(mc.jaga(db, langkah="po_produksi", alasan=f"  {ALASAN} ", user={}, hari_ini=HARI,
                                 per_model=per))
    assert alasan == ALASAN and len(temuan) == 1
    assert run(mc.jaga(db, langkah="po_produksi", alasan="", user={}, hari_ini=HARI, per_model={"M1": 20})) == ([], "")


def test_periksa_bahan_lewat_bom(db):
    _bom(db)
    t = run(mc.periksa_bahan(db, ["kain-lambat", "kain-umum", "kain-lama", "kain-baru", "kain-lepas"], hari_ini=HARI))
    assert [x["material_id"] for x in t] == ["kain-lambat"]
    assert t[0]["nama"] == "K-01 Kain Lambat" and {m["kelas"] for m in t[0]["model"]} == {"lambat", "mati"}
    assert "Kain Lambat" in mc.pesan(t, "pr_bahan") and "permintaan pembelian bahan" in mc.pesan(t, "pr_bahan")
    assert mc.bahan_baru([{"material_id": "a"}], [{"material_id": "a"}, {"material_id": "b"}, {}]) == ["b"]


def test_route_po_produksi_buat_dan_ubah(db, monkeypatch):
    from routes import production_pos as pp
    import core.po_lock as pl
    import routes.production_internal_adapter as pia
    user = {"id": "u1", "name": "Uji", "role": "owner"}

    async def _auth(_r):
        return dict(user)

    async def _nop(*a, **k):
        return None

    async def _buat(_db, body, _u):
        doc = {"id": f"po{len(db.production_pos.docs) + 1}", "business_type": body.get("business_type", "internal")}
        db.production_pos.docs.append(dict(doc))
        return doc

    async def _valid(_db, item):
        return {"id": item.get("model_id") or "M2", "code": "DA-2", "name": "Lambat"}, {"id": "s1", "code": "S"}
    monkeypatch.setattr(pp, "require_auth", _auth)
    monkeypatch.setattr(pp, "get_db", lambda: db)
    monkeypatch.setattr(pp, "today_wib", lambda: HARI)
    monkeypatch.setattr(pp, "assert_po_action", lambda *a, **k: None)
    monkeypatch.setattr(pp, "create_po_internal", _buat)
    monkeypatch.setattr(pp, "log_activity", _nop)
    monkeypatch.setattr(pl, "assert_po_open", _nop)
    monkeypatch.setattr(pia, "validate_internal_item", _valid)
    monkeypatch.setattr(pia, "explode_po_accessories_from_bom", _nop)
    body = {"business_type": "internal", "items": [{"model_id": "M2", "qty": 100}]}
    with pytest.raises(HTTPException) as e:
        run(pp.create_po(_Req(dict(body))))
    assert e.value.status_code == 428 and not db.production_pos.docs
    run(pp.create_po(_Req({**body, "alasan_merchandiser": ALASAN})))
    ev = db.production_pos.docs[0]["merchandiser_events"]
    assert ev[0]["alasan"] == ALASAN and ev[0]["langkah"] == "po_produksi" and ev[0]["oleh"]["id"] == "u1"
    run(pp.create_po(_Req({"business_type": "maklon", "buyer_id": "b1", "items": [{"model_id": "M2", "qty": 100}]})))
    assert "merchandiser_events" not in db.production_pos.docs[1]                 # PO maklon bukan barang DA
    # ubah: hanya TAMBAHAN qty yang diperiksa
    db.production_pos.docs = [{"id": "poX", "business_type": "internal", "status": "Draft", "po_number": "PO-X"}]
    db.po_items.docs = [{"id": "i1", "po_id": "poX", "model_id": "M2", "qty": 10}]
    run(pp.update_po("poX", _Req({"items": [{"id": "i1", "qty": 10}]})))            # tidak bertambah → lolos
    with pytest.raises(HTTPException) as e:
        run(pp.update_po("poX", _Req({"items": [{"id": "i1", "qty": 200}]})))
    assert e.value.status_code == 428 and db.po_items.docs[0]["qty"] == 10           # tidak ada yang tertulis
    run(pp.update_po("poX", _Req({"items": [{"id": "i1", "qty": 200}], "alasan_merchandiser": ALASAN})))
    po = db.production_pos.docs[0]
    assert db.po_items.docs[0]["qty"] == 200 and po["merchandiser_events"][0]["temuan"][0]["qty"] == 190
    assert "alasan_merchandiser" not in po


def test_route_pembelian_bahan(db, monkeypatch):
    from routes import dewi_procurement as dp, rahaza_po as rp, dewi_accessories_purchase as dap
    import utils.waktu as uw
    _bom(db)
    user = {"id": "u1", "name": "Uji", "role": "owner"}

    async def _auth(_r):
        return dict(user)

    async def _nop(*a, **k):
        return None

    async def _sama(_db, raw, **k):
        return [{"total_price": 0, **i} for i in raw]
    for m in (dp, rp, dap):
        monkeypatch.setattr(m, "require_auth", _auth)
        monkeypatch.setattr(m, "get_db", lambda: db)
    monkeypatch.setattr(uw, "today_wib", lambda: HARI)
    monkeypatch.setattr(dp, "today_wib", lambda: HARI)
    monkeypatch.setattr(rp, "today_wib", lambda: HARI)

    # Permintaan Pengadaan: buat
    async def _pr(_db, _u, body, **k):
        return {"id": "pr1", "status": "draft", "requested_by": "u1", "items": [dict(i) for i in body["items"]]}
    monkeypatch.setattr(dp, "build_pr_doc", _pr)
    monkeypatch.setattr(dp, "_norm_pr_items", _sama)
    with pytest.raises(HTTPException) as e:
        run(dp.create_request(_Req({"items": [{"material_id": "kain-lambat"}]})))
    assert e.value.status_code == 428 and "Kain Lambat" in e.value.detail
    run(dp.create_request(_Req({"items": [{"material_id": "kain-umum"}]})))       # dipakai model laris → lolos
    assert "merchandiser_events" not in db.dewi_procurement_requests.docs[0]
    db.dewi_procurement_requests.docs = []
    out = run(dp.create_request(_Req({"items": [{"material_id": "kain-lambat"}], "alasan_merchandiser": ALASAN})))
    assert out["merchandiser_events"][0]["langkah"] == "pr_bahan"
    # Permintaan Pengadaan: ubah draf — hanya bahan BARU yang diperiksa
    db.dewi_procurement_requests.docs[0]["items"] = [{"material_id": "kain-umum"}]
    with pytest.raises(HTTPException) as e:
        run(dp.update_request("pr1", _Req({"items": [{"material_id": "kain-umum"}, {"material_id": "kain-lambat"}]})))
    assert e.value.status_code == 428
    run(dp.update_request("pr1", _Req({"items": [{"material_id": "kain-umum"}, {"material_id": "kain-lambat"}],
                                       "alasan_merchandiser": ALASAN})))
    assert len(db.dewi_procurement_requests.docs[0]["merchandiser_events"]) == 2
    run(dp.update_request("pr1", _Req({"items": [{"material_id": "kain-lambat"}]})))   # sudah ada → lolos

    # PO pembelian langsung
    monkeypatch.setattr(rp, "_require_admin", _auth)
    monkeypatch.setattr(rp, "_norm_po_items", _sama)

    async def _sup(*a, **k):
        return {"supplier_id": "s1"}

    async def _no(*a, **k):
        return "PO-B-1"
    monkeypatch.setattr(rp, "_resolve_supplier", _sup)
    monkeypatch.setattr(rp, "_gen_po_number", _no)
    monkeypatch.setattr(rp, "_enrich_po", _nop)
    monkeypatch.setattr(rp, "log_activity", _nop)
    baris = [{"material_id": "kain-lambat", "qty_ordered": 10, "unit_cost": 1000}]
    with pytest.raises(HTTPException) as e:
        run(rp.create_po(_Req({"items": baris})))
    assert e.value.status_code == 428 and not db.rahaza_purchase_orders.docs
    out = run(rp.create_po(_Req({"items": baris, "alasan_merchandiser": ALASAN})))
    assert out["merchandiser_events"][0]["langkah"] == "po_bahan"

    # PR aksesoris
    async def _acc(_db, _u, body):
        doc = {"id": "acc-pr1", "status": "Draft", "items": body["items"]}
        db.acc_purchase_requests.docs.append(dict(doc))
        return doc
    monkeypatch.setattr(dap, "new_purchase_request", _acc)
    with pytest.raises(HTTPException) as e:
        run(dap.create_purchase_request(_Req({"items": [{"acc_id": "kain-lambat", "qty_requested": 5}]})))
    assert e.value.status_code == 428 and not db.acc_purchase_requests.docs
    run(dap.create_purchase_request(_Req({"items": [{"acc_id": "kain-lambat", "qty_requested": 5}],
                                          "alasan_merchandiser": ALASAN})))
    assert db.acc_purchase_requests.docs[0]["merchandiser_events"][0]["alasan"] == ALASAN


def test_route_check_tanpa_simpan(db, monkeypatch):
    from routes import merchandiser as rt
    _bom(db)

    async def _auth(_r):
        return {"id": "u1", "role": "owner"}
    monkeypatch.setattr(rt, "require_auth", _auth)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "today_wib", lambda: HARI)
    out = run(rt.get_check(SimpleNamespace(), langkah="po_produksi", model="M2:100,M1:20,rusak", varian=None,
                           bahan="kain-lambat,kain-umum"))
    assert out["perlu_alasan"] and {t.get("model_id") or t.get("material_id") for t in out["temuan"]} == \
        {"M2", "kain-lambat"}
    assert out["min_alasan"] == 10 and out["kunci_alasan"] == "alasan_merchandiser"
    aman = run(rt.get_check(SimpleNamespace(), langkah="po_produksi", model="M1:20", varian=None, bahan=None))
    assert aman["perlu_alasan"] is False and aman["temuan"] == [] and aman["pesan"] == ""


def test_jejak_pengaman_dan_route(db, monkeypatch):
    from routes import merchandiser as rt
    ev = lambda pada, alasan: {"langkah": "po_produksi", "alasan": alasan, "pada": pada,       # noqa: E731
                               "oleh": {"id": "u1", "nama": "Uji"}, "temuan": [{"kode": "DA-2", "nama": "Lambat"}]}
    db.production_pos.docs = [{"id": "p1", "po_number": "PO-1", "merchandiser_events": [
        ev("2026-11-10T02:00:00+00:00", ALASAN), ev("2026-10-01T02:00:00+00:00", "lama sekali alasannya")]}]
    db.rahaza_purchase_orders.docs = [{"id": "b1", "po_number": "PO-B-1", "merchandiser_events": [
        {**ev("2026-11-11T02:00:00+00:00", "stok kain untuk model baru"), "langkah": "po_bahan",
         "temuan": [{"material_id": "kain-lambat", "nama": "K-01 Kain Lambat"}]}]}]
    rows = run(mc.jejak_pengaman(db, sejak=datetime(2026, 11, 5, tzinfo=timezone.utc)))
    assert [(r["jenis"], r["nomor"], r["menu"]) for r in rows] == [
        ("PO pembelian", "PO-B-1", "proc-purchase-orders"), ("PO produksi", "PO-1", "prod-pos-internal")]
    assert rows[1]["alasan"] == ALASAN and rows[1]["oleh"] == "Uji" and rows[1]["barang"] == ["DA-2"]
    assert rows[0]["barang"] == ["K-01 Kain Lambat"]

    async def _auth(_r):
        return {"id": "u1", "role": "owner"}
    monkeypatch.setattr(rt, "require_auth", _auth)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "today_wib", lambda: HARI)
    out = run(rt.get_pengaman(SimpleNamespace(), hari=2))                     # 11–12 Nov WIB
    assert out["jumlah"] == 1 and out["baris"][0]["nomor"] == "PO-B-1"


def test_alat_pengaman_dan_jejak():
    ab.muat_semua_alat()
    c = ab._DAFTAR["cek_pengaman_merchandiser"]
    ctx = _Ctx()
    run(c.handler(ctx, {"langkah": "pr_bahan", "model": [{"id": "M2", "qty": 100}], "varian": [{"id": "v1", "qty": 2.5}],
                        "bahan_ids": ["kain-1", "kain-2"]}))
    assert ctx.calls[0] == ("GET", "/api/merchandiser/check", {"langkah": "pr_bahan", "model": "M2:100",
                                                               "varian": "v1:2.5", "bahan": "kain-1,kain-2"})
    j = ab._DAFTAR["jejak_pengaman_merchandiser"]
    ctx = _Ctx()
    run(j.handler(ctx, {}))
    assert ctx.calls[0] == ("GET", "/api/merchandiser/pengaman", {"hari": 7})
    assert not c.adalah_tindakan and not j.adalah_tindakan
