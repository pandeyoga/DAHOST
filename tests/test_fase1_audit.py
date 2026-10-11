"""Uji FASE 1 PLAN_PERBAIKAN_AUDIT (T-04, T-06, T-07, T-08, T-10, T-14a) lewat API nyata + DB.

Jalankan:  cd /app/backend && set -a && . .env && set +a && python ../tests/test_fase1_audit.py
Membuat data uji lalu membersihkannya sendiri (restore seed tetap disarankan sesudahnya).
"""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timezone

import requests

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

API = os.environ.get("API_URL") or "http://localhost:8001"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def login(email, pw):
    r = requests.post(f"{API}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def check(name, cond, info=""):
    print(("PASS" if cond else "FAIL"), name, info if not cond else "")
    if not cond:
        FAILS.append(name)


FAILS = []
H = login("admin@garment.com", "Admin@123")
H_ACC = login("uji.accounting@dewiaditya.id", "Dewi@123")
uid = lambda: str(uuid.uuid4())  # noqa: E731
now = datetime.now(timezone.utc)


async def t04_product_costing():
    from core import product_costing as pc
    model_id, size_id = uid(), uid()
    mat_ok = uid()
    await db.rahaza_models.insert_one({"id": model_id, "code": f"UJI-T04-{model_id[:4]}", "name": "Model Uji T04",
                                       "active": True, "retail_price": 100000, "created_at": now})
    await db.rahaza_sizes.insert_one({"id": size_id, "code": "UJI", "name": "UJI"})
    await db.rahaza_materials.insert_one({"id": mat_ok, "code": f"UJI-MAT-{mat_ok[:4]}", "name": "Kain uji", "type": "fabric",
                                          "unit": "m", "base_unit": "m", "unit_cost": 20000, "cost_method": "moving_average", "hpp": 0})
    fg_id = uid()
    await db.rahaza_materials.insert_one({"id": fg_id, "code": f"UJI-FG-{fg_id[:4]}", "name": "FG uji", "type": "fg",
                                          "model_id": model_id, "size_id": size_id, "hpp": 0, "hpp_source": "none"})
    bom_id = uid()
    await db.rahaza_boms.insert_one({"id": bom_id, "model_id": model_id, "size_id": size_id, "size_code": "UJI", "active": True,
                                     "is_active": True, "version": 1, "materials": [
                                         {"material_id": mat_ok, "code": f"UJI-MAT-{mat_ok[:4]}", "name": "Kain uji", "qty": 1.5, "unit": "m", "material_type": "fabric"},
                                         {"material_id": None, "code": "", "name": "Baris tanpa master", "qty": 2, "unit": "pcs", "material_type": "accessory"},
                                     ]})
    try:
        d = await pc.compute_model_cost(db, model_id, with_candidates=False)
        row = d["sizes"][0]
        check("T-04 computable=False bila ada baris unlinked", row["computable"] is False,
              str({k: row[k] for k in ("computable", "unvalued_count")}))
        check("T-04 gap bom_line_unlinked ada", any(g["code"] == "bom_line_unlinked" for g in d["gaps"]))
        res = await pc.apply_model_cost(db, model_id, {"id": "uji", "name": "uji"})
        check("T-04 apply menolak size tidak computable", res["ok"] is False and res["skipped"], str(res.get("skipped")))
        m = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0, "hpp_bom": 1})
        fg = await db.rahaza_materials.find_one({"id": fg_id}, {"_id": 0, "hpp": 1, "hpp_source": 1})
        check("T-04 master & FG tidak berubah", not m.get("hpp_bom") and fg["hpp"] == 0 and fg["hpp_source"] == "none", str((m, fg)))
        gap = next((g for g in d["gaps"] if g["code"] == "cmt_rate_missing"), None)
        check("T-14b gap cmt_rate_missing menunjuk layar Biaya Jahit SPK", gap is not None and gap["target"] == "prod-sewing-cost", str(gap))
    finally:
        await db.rahaza_models.delete_one({"id": model_id})
        await db.rahaza_sizes.delete_one({"id": size_id})
        await db.rahaza_materials.delete_many({"id": {"$in": [mat_ok, fg_id]}})
        await db.rahaza_boms.delete_one({"id": bom_id})
        await db.product_cost_snapshots.delete_many({"model_id": model_id})


async def t06_mirror_put():
    po_id = uid()
    await db.dewi_maklon_pos.insert_one({"id": po_id, "po_number": f"UJI-T06-{po_id[:6]}", "status": "draft", "mirror_of": "production_pos",
                                         "production_po_id": po_id, "client_id": "x", "client_name": "Uji", "items": [], "total_qty": 0,
                                         "total_value": 0, "created_at": now, "updated_at": now})
    po2 = uid()
    await db.dewi_maklon_pos.insert_one({"id": po2, "po_number": f"UJI-T06B-{po2[:6]}", "status": "draft", "client_id": "x", "client_name": "Uji",
                                         "items": [], "total_qty": 0, "total_value": 0, "created_at": now, "updated_at": now})
    try:
        r = requests.put(f"{API}/api/dewi/maklon/pos/{po_id}", headers=H, json={"notes": "coba"}, timeout=30)
        check("T-06 PUT mirror → 409", r.status_code == 409, f"{r.status_code} {r.text[:200]}")
        check("T-06 pesan & target ada", r.status_code == 409 and r.json()["detail"].get("target") == "maklon-pos-engine")
        r2 = requests.put(f"{API}/api/dewi/maklon/pos/{po2}", headers=H, json={"notes": "coba"}, timeout=30)
        check("T-06 PUT PO non-mirror → 200", r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}")
    finally:
        await db.dewi_maklon_pos.delete_many({"id": {"$in": [po_id, po2]}})


async def t07_delete_job():
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    jid = uid()
    await db.production_jobs.insert_one({"id": jid, "job_number": f"UJI-T07-{jid[:6]}", "status": "Completed", "created_at": now})
    await db.production_job_items.insert_one({"id": uid(), "job_id": jid})
    await db.rahaza_wip_events.insert_one({"id": uid(), "job_id": jid, "event_type": "complete"})
    await db.rahaza_hpp_snapshots.insert_one({"id": uid(), "job_id": jid})
    await db.fg_cost_layers.insert_one({"id": uid(), "gl_job_id": jid, "material_id": "x", "qty_in": 1, "qty_remaining": 1})
    lines = [{"account_code": "1-1404", "debit": 1000, "credit": 0, "description": "uji"},
             {"account_code": "1-1403", "debit": 0, "credit": 1000, "description": "uji"}]
    je = await _create_posted_je(db, date.today(), "uji T07", "production_job", f"wip_fg_job:{jid}", lines, {"id": "uji", "name": "uji"})
    check("T-07 setup: JE dibuat", je.get("ok"), str(je))
    try:
        r = requests.delete(f"{API}/api/production-jobs/{jid}", headers=H, timeout=30)
        check("T-07 DELETE job → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        je_doc = await db.rahaza_journal_entries.find_one({"id": je["je_id"]}, {"_id": 0, "status": 1})
        check("T-07 JE voided", (je_doc or {}).get("status") == "voided", str(je_doc))
        check("T-07 cermin journal_lines hilang", await db.rahaza_journal_lines.count_documents({"je_id": je["je_id"]}) == 0)
        check("T-07 layer/snapshot/wip/items 0",
              await db.fg_cost_layers.count_documents({"gl_job_id": jid}) == 0
              and await db.rahaza_hpp_snapshots.count_documents({"job_id": jid}) == 0
              and await db.rahaza_wip_events.count_documents({"job_id": jid}) == 0
              and await db.production_job_items.count_documents({"job_id": jid}) == 0)
        check("T-07 job terhapus", await db.production_jobs.count_documents({"id": jid}) == 0)
    finally:
        await db.production_jobs.delete_one({"id": jid})
        await db.production_job_items.delete_many({"job_id": jid})
        await db.rahaza_wip_events.delete_many({"job_id": jid})
        await db.rahaza_hpp_snapshots.delete_many({"job_id": jid})
        await db.fg_cost_layers.delete_many({"gl_job_id": jid})
        await db.rahaza_journal_lines.delete_many({"je_id": je.get("je_id")})
        await db.rahaza_journal_entries.delete_one({"id": je.get("je_id")})

    # periode terkunci → 409
    jid2 = uid()
    await db.production_jobs.insert_one({"id": jid2, "job_number": f"UJI-T07L-{jid2[:6]}", "status": "Completed", "created_at": now})
    je2 = await _create_posted_je(db, date.today(), "uji T07 lock", "production_job", f"wip_fg_job:{jid2}", lines, {"id": "uji", "name": "uji"})
    ym = date.today().strftime("%Y-%m")
    per = await db.rahaza_periods.find_one({"period_code": ym}, {"_id": 0, "status": 1})
    await db.rahaza_periods.update_one({"period_code": ym}, {"$set": {"status": "locked"}})
    try:
        r = requests.delete(f"{API}/api/production-jobs/{jid2}", headers=H, timeout=30)
        check("T-07 job di periode terkunci → 409", r.status_code == 409, f"{r.status_code} {r.text[:200]}")
        check("T-07 job TIDAK terhapus saat 409", await db.production_jobs.count_documents({"id": jid2}) == 1)
    finally:
        await db.rahaza_periods.update_one({"period_code": ym}, {"$set": {"status": (per or {}).get("status", "open")}})
        await db.production_jobs.delete_one({"id": jid2})
        await db.rahaza_journal_lines.delete_many({"je_id": je2.get("je_id")})
        await db.rahaza_journal_entries.delete_one({"id": je2.get("je_id")})


def t08_roles():
    r = requests.post(f"{API}/api/hr/expenses/claims/bulk-approve", headers=H_ACC, json={"claim_ids": ["x"]}, timeout=30)
    check("T-08 accounting bulk-approve klaim → 200 (bukan 403)", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    r = requests.post(f"{API}/api/hr/travel/requests/bulk-approve", headers=H_ACC, json={"request_ids": ["x"]}, timeout=30)
    check("T-08 accounting bulk-approve perjalanan → bukan 403", r.status_code != 403, f"{r.status_code} {r.text[:150]}")
    r = requests.get(f"{API}/api/rahaza/ar-360/summary", headers=H_ACC, timeout=30)
    check("T-08 accounting AR-360 → bukan 403", r.status_code != 403, f"{r.status_code} {r.text[:150]}")


async def t10_unique_je():
    from routes.rahaza_posting import _create_posted_je
    ref = f"uji-t10:{uid()}"
    lines = [{"account_code": "1-1404", "debit": 500, "credit": 0}, {"account_code": "1-1403", "debit": 0, "credit": 500}]
    results = await asyncio.gather(*[
        _create_posted_je(db, date.today(), "uji T10", "uji_module", ref, lines, {"id": "uji", "name": "uji"}) for _ in range(5)])
    ids = {r.get("je_id") for r in results}
    n = await db.rahaza_journal_entries.count_documents({"source_module": "uji_module", "source_ref": ref, "status": {"$ne": "voided"}})
    check("T-10 5 posting paralel sumber sama → 1 JE", n == 1 and len(ids) == 1 and all(r.get("ok") for r in results), f"n={n} ids={ids}")
    await db.rahaza_journal_lines.delete_many({"source_ref": ref})
    await db.rahaza_journal_entries.delete_many({"source_ref": ref})


async def t14a_cmt_zero_rate():
    from routes.production_maklon_bridge import mature_ap_from_cmt_receipt
    rid, po_id, item_id = uid(), uid(), uid()
    await db.production_pos.insert_one({"id": po_id, "po_number": f"UJI-T14-{po_id[:6]}", "business_type": "internal", "status": "In Production"})
    await db.po_items.insert_one({"id": item_id, "po_id": po_id, "sku": "UJI-SKU", "qty": 10, "cmt_price_snapshot": 0})
    await db.cmt_receipts.insert_one({"id": rid, "receipt_code": f"RCV-UJI-{rid[:6]}", "po_id": po_id, "status": "approved",
                                      "cmt_name": "CMT Uji", "total_shipped_by_cmt": 10, "receipt_date": date.today().isoformat()})
    await db.cmt_receipt_lines.insert_one({"id": uid(), "receipt_id": rid, "po_item_id": item_id, "sku_code": "UJI-SKU",
                                           "qty_actual": 10, "reject_qty": 0})
    try:
        res = await mature_ap_from_cmt_receipt(db, rid, {"id": "uji", "name": "uji"})
        pay = await db.dewi_cmt_payments.find_one({"source_receipt_id": rid}, {"_id": 0})
        check("T-14a tagihan CMT tarif 0 berbendera variance", bool(pay) and pay.get("variance_flagged") is True, str(res)[:300])
        check("T-14a alasan 'tarif CMT 0 untuk 10 pcs' tercatat",
              bool(pay) and any("tarif CMT 0 untuk 10 pcs" in r for r in (pay.get("variance_reasons") or [])), str((pay or {}).get("variance_reasons")))
    finally:
        pay = await db.dewi_cmt_payments.find_one({"source_receipt_id": rid}, {"_id": 0, "id": 1})
        if pay:
            await db.rahaza_journal_lines.delete_many({"source_ref": {"$regex": pay["id"]}})
            await db.rahaza_journal_entries.delete_many({"source_ref": {"$regex": pay["id"]}})
            await db.dewi_cmt_payments.delete_one({"id": pay["id"]})
        await db.cmt_receipts.delete_one({"id": rid})
        await db.cmt_receipt_lines.delete_many({"receipt_id": rid})
        await db.po_items.delete_one({"id": item_id})
        await db.production_pos.delete_one({"id": po_id})


async def main():
    await t04_product_costing()
    await t06_mirror_put()
    await t07_delete_job()
    t08_roles()
    await t10_unique_je()
    await t14a_cmt_zero_rate()
    print("\nGAGAL:", FAILS if FAILS else "tidak ada")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
