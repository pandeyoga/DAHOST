"""MKT-INTI · cara input omzet (keputusan owner 9 Nov 2026: Q-4, Q-5) + M-20 + Q-6.

  Q-5  Mode input per toko: toko "Impor pesanan" menolak rekap TOTAL yang diketik (409, override
       SPV tetap boleh), tidak mendapat tugas input manual, dan PIC diingatkan bila H-1 belum diimpor.
  Q-4  Pesanan manual (Order Terpadu) toko marketplace wajib No. Pesanan platform + tanggal pesanan;
       nomor ganda ditolak; toko non-marketplace tetap boleh tanpa nomor (MAN-…).
  M-20 Rekap lewat aksi tugas: lingkup toko, kunci periode, dan mode toko dijaga sama seperti entri manual.
  Q-6  Basis tanggal omzet = tanggal pesanan dibuat (pesanan 23.30 tetap di hari itu).
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from _mkt_uji import DB, PIC, SA, SPV, Req, acc, patch_route, run  # noqa: E402


@pytest.fixture
def db():
    d = DB()
    d.marketing_platform_accounts.docs += [acc("TTK-01"), acc("WA-01", platform="whatsapp"),
                                           acc("TTK-02", sales_input_mode="rekap_manual")]
    # TTK-01 pernah impor pesanan ⇒ mode efektif "impor_pesanan"
    d.marketing_orders.docs.append({"id": "o1", "account_id": "TTK-01", "order_id": "111",
                                    "_import_source_type": "marketplace_orders", "status": "completed",
                                    "order_date": datetime(2026, 8, 1, tzinfo=timezone.utc)})
    return d


# ── Q-5 ───────────────────────────────────────────────────────────────────────────────────────
def test_q5_mode_toko_diturunkan_dari_data_atau_pilihan(db):
    from core import marketing_input_mode as M
    accs = {a["id"]: a for a in db.marketing_platform_accounts.docs}
    assert run(M.mode_toko(db, accs["TTK-01"])) == M.IMPOR
    assert run(M.mode_toko(db, accs["WA-01"])) == M.MANUAL
    assert run(M.mode_toko(db, accs["TTK-02"])) == M.MANUAL           # pilihan tersimpan menang


def test_q5_rekap_manual_ditolak_untuk_toko_impor_override_spv_tetap_boleh(db, monkeypatch):
    import routes.marketing_sales as ms
    from routes.marketing_shared import SalesDataEntry
    patch_route(monkeypatch, ms, db, user=SPV)
    body = SalesDataEntry(account_id="TTK-01", date="2026-08-05", revenue_type="total",
                          revenue=500_000, orders=5)
    with pytest.raises(HTTPException) as e:
        run(ms.create_sales_data(body, Req(SPV), override=False, override_reason=None))
    assert e.value.status_code == 409 and "Impor pesanan" in e.value.detail
    # toko rekap manual tetap bisa
    run(ms.create_sales_data(SalesDataEntry(account_id="WA-01", date="2026-08-05",
                                            revenue_type="total", revenue=500_000, orders=5),
                             Req(SPV), override=False, override_reason=None))
    assert any(d["account_id"] == "WA-01" for d in db.marketing_sales_data.docs)


def test_q5_penjadwal_tidak_membuat_tugas_input_untuk_toko_impor(db, monkeypatch):
    from utils import scheduler as sch
    import routes.rahaza_notifications as rn
    sent = []

    async def _pub(_db, **kw):
        sent.append(kw)
    monkeypatch.setattr(sch, "get_db", lambda: db)
    monkeypatch.setattr(rn, "publish_notification", _pub)
    for a in db.marketing_platform_accounts.docs:
        a["pic_user_id"] = "u-pic"
    run(sch.job_auto_create_marketing_tasks())
    tasks = {t["account_id"] for t in db.marketing_tasks.docs if t.get("related_entity") == "sales_data"}
    assert "TTK-01" not in tasks and {"WA-01", "TTK-02"} <= tasks
    assert any(n.get("type_") == "marketing_import_reminder" for n in sent)


# ── Q-4 ───────────────────────────────────────────────────────────────────────────────────────
def _order_env(db, monkeypatch, user=SA):
    import routes.marketing_orders_routes as mo
    patch_route(monkeypatch, mo, db, user=user)

    async def _link(_db, **_k):
        return {"catalog_item_id": "c1", "variant_id": None, "fg_material_id": "fg1", "variant_sku": "S1",
                "product_name": "Kaos", "variation": "", "model_id": None, "harga_jual": 100_000.0,
                "resolved_by": "catalog_item_id"}

    async def _noop(*_a, **_k):
        return {}
    monkeypatch.setattr(mo, "_resolve_order_link", _link)
    import core.marketing_daily_rollup as rollup
    monkeypatch.setattr(rollup, "recompute_for_orders", _noop)
    return mo


def test_q4_pesanan_manual_toko_marketplace_wajib_nomor_dan_tanggal(db, monkeypatch):
    mo = _order_env(db, monkeypatch)
    base = dict(platform="tiktok", account_id="TTK-01", customer_name="Uji", catalog_item_id="c1",
                quantity=1, price_final=100_000)
    with pytest.raises(HTTPException) as e:
        run(mo.create_order(mo.OrderCreateBody(**base), Req()))
    assert e.value.status_code == 400 and "No. Pesanan" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(mo.create_order(mo.OrderCreateBody(**base, order_id="999"), Req()))
    assert e.value.status_code == 400 and "tanggal" in e.value.detail
    out = run(mo.create_order(mo.OrderCreateBody(**base, order_id="999", order_date="2026-08-03 23:30"),
                              Req()))
    assert out["order_id"] == "999" and str(out["order_date"]).startswith("2026-08-03")   # Q-6
    with pytest.raises(HTTPException) as e:                                 # nomor ganda
        run(mo.create_order(mo.OrderCreateBody(**base, order_id="111", order_date="2026-08-03"), Req()))
    assert e.value.status_code == 409


def test_q4_toko_non_marketplace_tetap_boleh_tanpa_nomor(db, monkeypatch):
    mo = _order_env(db, monkeypatch)
    out = run(mo.create_order(mo.OrderCreateBody(platform="whatsapp", account_id="WA-01",
                                                 customer_name="Uji", catalog_item_id="c1",
                                                 quantity=1, price_final=100_000), Req()))
    assert out["order_id"].startswith("MAN-")


def test_q4_pesanan_manual_toko_orang_lain_ditolak(db, monkeypatch):
    db.marketing_platform_accounts.docs[1]["pic_user_id"] = PIC["id"]
    mo = _order_env(db, monkeypatch, user=PIC)
    with pytest.raises(HTTPException) as e:
        run(mo.create_order(mo.OrderCreateBody(platform="tiktok", account_id="TTK-01", customer_name="U",
                                               catalog_item_id="c1", order_id="5", order_date="2026-08-03"),
                            Req(PIC)))
    assert e.value.status_code == 403


# ── M-20 ──────────────────────────────────────────────────────────────────────────────────────
def _task(db, aid, date="2026-08-05"):
    db.marketing_tasks.docs.append({"id": f"t-{aid}", "status": "to_do", "action_type": "submit_form",
                                    "related_entity": "sales_data", "account_id": aid,
                                    "related_form_data": {"account_id": aid, "date": date}})
    return f"t-{aid}"


def test_m20_rekap_lewat_tugas_dijaga_kunci_periode_lingkup_dan_mode(db, monkeypatch):
    import routes.marketing_tasks as mt
    from routes.marketing_shared import TaskCompleteAction
    patch_route(monkeypatch, mt, db)
    db.marketing_period_locks.docs.append({"account_id": "WA-01", "period": "2026-08", "locked": True})
    with pytest.raises(HTTPException) as e:
        run(mt._complete_task_action_locked(db, _task(db, "WA-01"), TaskCompleteAction(
            action_data={"revenue": 1, "orders": 1}), dict(SA)))
    assert e.value.status_code == 423
    with pytest.raises(HTTPException) as e:
        run(mt._complete_task_action_locked(db, _task(db, "TTK-01"), TaskCompleteAction(
            action_data={"revenue": 1, "orders": 1}), dict(SA)))
    assert e.value.status_code == 409                                      # toko impor pesanan
    db.marketing_platform_accounts.docs[2]["pic_user_id"] = "lain"
    with pytest.raises(HTTPException) as e:
        run(mt._complete_task_action_locked(db, _task(db, "TTK-02"), TaskCompleteAction(
            action_data={"revenue": 1, "orders": 1}), dict(PIC)))
    assert e.value.status_code == 403


# ── Q-6 ───────────────────────────────────────────────────────────────────────────────────────
def test_q6_basis_tanggal_omzet_tanggal_pesanan_dibuat():
    from core import marketing_daily_rollup as R
    assert R.order_date_key(datetime(2026, 8, 3, 23, 30, tzinfo=timezone.utc)) == "2026-08-03"
    assert R.order_date_key("2026-08-03T23:30:00") == "2026-08-03"


def test_q5_impor_rekap_harian_ke_toko_impor_pesanan_ditolak(db, monkeypatch):
    from _mkt_uji import csv_bytes, import_file, patch_import
    md = patch_import(monkeypatch, db)
    sd = csv_bytes([["date", "revenue_type", "revenue", "orders"], ["2026-08-04", "total", 1_234_567, 12]])
    _sid, res = run(import_file(md, sd, "rekap.csv", "sales_daily", "TTK-01", on_duplicate="update"))
    assert res["inserted"] == 0 and res["rejected"] == 1
    _sid, res = run(import_file(md, sd, "rekap.csv", "sales_daily", "TTK-02", on_duplicate="update"))
    assert res["inserted"] == 1                                    # toko rekap manual tetap bisa
