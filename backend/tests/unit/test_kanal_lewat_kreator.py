"""Omzet LEWAT KREATOR di laporan kanal (owner 11 Nov 2026: "Yes, add it").

TikTok menulis kanal (LIVE/Videos/Product cards) dan kreator ("Creator Handle") di dua kolom
terpisah. "Lewat kreator" adalah lapisan di ATAS kanal: bagian dari omzet kanalnya, tidak pernah
dijumlah ke total (itu menghitung satu penjualan dua kali). Semua data SINTETIS.
"""
from datetime import datetime, timezone

from _mkt_uji import DB, SA, Req, acc, patch_route, run  # noqa: E402
from core import marketing_account_scope as scope  # noqa: E402
from core import ukuran_penjualan as U  # noqa: E402

HARI = "2026-11-03"


def _o(oid, aid, amount, channel, handle=None, creator_id=None):
    o = {"id": oid, "order_id": oid, "account_id": aid, "status": "completed", "_tanggal": HARI,
         "order_date": datetime(2026, 11, 3, 10, tzinfo=timezone.utc), "order_channel": channel,
         "revenue_product": float(amount), "quantity": 1}
    if handle:
        o["creator_handle"] = handle
    if creator_id:
        o["creator_id"] = creator_id
    return o


ORDERS = [_o("a", "TTK-01", 500_000, "video", "@kreator.satu", "cr1"),
          _o("b", "TTK-01", 300_000, "video"),
          _o("c", "TTK-01", 200_000, "live", "Kreator.Satu"),   # akun sama, ejaan beda
          _o("d", "TTK-01", 100_000, "live", "@kreator_dua"),
          _o("e", "SHP-01", 900_000, "other")]


def test_lewat_kreator_adalah_bagian_kanal_bukan_tambahan():
    k = {c["kunci"]: c for c in U.rincian_kanal(ORDERS)}
    assert k["video"]["omzet"] == 800_000 and k["video"]["lewat_kreator"] == 500_000
    assert k["live"]["omzet"] == 300_000 and k["live"]["lewat_kreator"] == 300_000
    assert k["live"]["pesanan_kreator"] == 2 and k["other"]["lewat_kreator"] == 0
    total = sum(c["omzet"] for c in k.values())
    assert total == 2_000_000                                     # = jumlah pesanan; kreator tidak menambah
    assert all(c["lewat_kreator"] <= c["omzet"] for c in k.values())


def test_ringkas_kreator_hanya_jumlah_dan_kreator_belum_terdaftar():
    r = U.ringkas_kreator(ORDERS)
    assert r == {"omzet": 800_000, "pesanan": 3, "kreator": 2, "kreator_belum_terdaftar": 2}
    assert "kreator" not in str([v for v in r.values() if isinstance(v, str)])  # tanpa nama/akun


def test_kanal_per_toko_menyertakan_lewat_kreator():
    per = {r["account_id"]: r for r in U.kanal_per_toko([], ORDERS, {"TTK-01": acc("TTK-01")})}
    assert per["TTK-01"]["lewat_kreator"] == 800_000 and per["SHP-01"]["lewat_kreator"] == 0


def test_akun_kreator_dicocokkan_ke_master_seperti_impor():
    db = DB()
    db.marketing_kol_creators.docs.append({"id": "cr1", "name": "Kreator Satu",
                                           "platforms": {"tiktok": "kreator.satu"},
                                           "creator_code": "KOL-07"})
    assert run(scope.creator_for_handle(db, "@Kreator.Satu"))["id"] == "cr1"
    assert run(scope.creator_for_handle(db, "kol-07"))["id"] == "cr1"
    assert run(scope.creator_for_handle(db, "@orang_lain")) is None
    assert run(scope.creator_for_handle(db, "")) is None


def test_pesanan_manual_menautkan_kreator_terdaftar(monkeypatch):
    import core.marketing_daily_rollup as rollup
    import routes.marketing_orders_routes as mo
    db = DB()
    db.marketing_platform_accounts.docs.append(acc("WA-01", platform="whatsapp"))
    db.marketing_kol_creators.docs.append({"id": "cr1", "name": "Kreator Satu",
                                           "platforms": {"tiktok": "kreator.satu"}})
    patch_route(monkeypatch, mo, db, user=SA)

    async def _link(_db, **_k):
        return {"catalog_item_id": "c1", "variant_id": None, "fg_material_id": "fg1", "variant_sku": "S1",
                "product_name": "Kaos", "variation": "", "model_id": None, "harga_jual": 100_000.0,
                "resolved_by": "catalog_item_id"}

    async def _noop(*_a, **_k):
        return {}
    monkeypatch.setattr(mo, "_resolve_order_link", _link)
    monkeypatch.setattr(rollup, "recompute_for_orders", _noop)
    base = dict(platform="whatsapp", account_id="WA-01", customer_name="Uji", catalog_item_id="c1",
                quantity=1, price_final=100_000, order_channel="affiliate")
    out = run(mo.create_order(mo.OrderCreateBody(**base, creator_handle="@kreator.satu"), Req()))
    assert out["creator_id"] == "cr1" and out["creator_name"] == "Kreator Satu"
    out = run(mo.create_order(mo.OrderCreateBody(**base, creator_handle="@belum.ada"), Req()))
    assert out["creator_id"] is None and out["creator_handle"] == "@belum.ada"
