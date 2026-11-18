"""Uji unit HERMETIK — Batal COD di Monitoring kirim (18 Nov 2026, owner: "tambahkan berkas batal cod … nanti muncul
ke data mana saya ikuti rekomendasi anda").

Nilai uji = nilai NYATA di VPS (metode bayar "Bayar di tempat" / "COD (Bayar di Tempat)", alasan "Pengiriman paket
gagal", "Dibatalkan secara otomatis oleh sistem Shopee. Alasan: Pengiriman gagal", "Tidak perlu lagi", …).

Jalankan:  cd backend && python -m pytest tests/unit/test_batal_cod.py -q
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from core import batal_cod as bc  # noqa: E402

USER = {"id": "u1", "name": "Uji", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


def test_cod_dikenali_dari_metode_bayar_nyata():
    assert bc.is_cod({"payment_method": "Bayar di tempat"})
    assert bc.is_cod({"payment_method": "COD (Bayar di Tempat)"})
    assert bc.is_cod({"payment_method": "Cash on Delivery"})
    for m in ("QRIS", "Transfer bank", "SPayLater", "TikTok Shop Balance + QRIS", "", None):
        assert not bc.is_cod({"payment_method": m}), m


def test_jenis_batal_cod_gagal_kirim_didahulukan():
    g = lambda r: bc.jenis_batal_cod({"cancel_reason": r})  # noqa: E731
    assert g("Pengiriman paket gagal") == "gagal_kirim"
    assert g("Dibatalkan secara otomatis oleh sistem Shopee. Alasan: Pengiriman gagal") == "gagal_kirim"
    assert g("Paket ditolak pembeli") == "gagal_kirim"
    assert g("Tidak perlu lagi") == "batal_pembeli"
    assert g("Perlu mengubah alamat pengiriman") == "batal_pembeli"
    assert g("Dibatalkan oleh Pembeli. Alasan: Alasan Lainnya") == "batal_pembeli"
    assert g("Ongkir mahal") == "batal_pembeli"
    assert g("") == "lainnya" and g("Stok habis") == "lainnya"
    assert bc.jenis_batal_cod({"cancelation_return_type": "Failed delivery"}) == "gagal_kirim"
    assert bc.persen(1, 3) == 33.3 and bc.persen(0, 0) == 0.0


def _order(oid, pm, status, reason="", value=100000, acc="A1"):
    return {"id": oid, "order_id": oid, "account_id": acc, "account_name": "Toko A", "platform": "tiktok",
            "payment_method": pm, "status": status, "cancel_reason": reason, "revenue_product": value,
            "order_date": "2026-11-10T00:00:00", "quantity": 1}


def test_monitor_kelompok_batal_cod_dan_rekap_per_toko(monkeypatch):
    import routes.marketing_orders_routes as mo
    db = fm.FakeDB()
    db.marketing_orders.docs += [
        _order("O1", "Bayar di tempat", "cancelled", "Pengiriman paket gagal", 150000),
        _order("O2", "Bayar di tempat", "cancelled", "Tidak perlu lagi", 90000),
        _order("O3", "Bayar di tempat", "completed"),
        _order("O4", "COD (Bayar di Tempat)", "shipped"),
        _order("O5", "QRIS", "cancelled", "Pesanan dibatalkan karena pembeli terlambat membayar"),
    ]

    async def auth(req):
        return USER

    async def noop():
        return None

    async def accounts(db_, user, base=None, limit=200):
        return [{"id": "A1", "account_code": "TK-A", "account_name": "Toko A", "platform": "tiktok"}]

    async def scope(db_, user, q):
        return q
    monkeypatch.setattr(mo, "require_auth", auth)
    monkeypatch.setattr(mo, "get_db", lambda: db)
    monkeypatch.setattr(mo, "ensure_order_indexes", noop)
    monkeypatch.setattr(mo._scope, "visible_accounts", accounts)
    monkeypatch.setattr(mo._scope, "scope_filter", scope)
    out = run(mo.fulfillment_monitor(fm.FakeRequest(), account_id=None, bucket="batal_cod", as_of=None,
                                     page=1, page_size=50))
    t = out["totals"]
    assert (t["cod"], t["batal_cod"], t["batal_cod_gagal_kirim"], t["nilai_batal_cod"], t["batal"]) == (4, 2, 1, 240000, 3)
    assert t["persen_batal_cod"] == 50.0
    rows = {r["order_id"]: r for r in out["rows"]}
    assert set(rows) == {"O1", "O2"}                                      # QRIS batal bukan batal COD
    assert rows["O1"]["jenis_batal"] == "gagal_kirim" and rows["O1"]["jenis_batal_label"] == "Gagal kirim / ditolak"
    assert rows["O2"]["jenis_batal"] == "batal_pembeli" and rows["O2"]["payment_method"] == "Bayar di tempat"
    s = out["per_store"][0]
    assert (s["cod"], s["batal_cod"], s["batal_cod_gagal_kirim"]) == (4, 2, 1)
    assert any("Batal COD" in n for n in out["data_notes"])
