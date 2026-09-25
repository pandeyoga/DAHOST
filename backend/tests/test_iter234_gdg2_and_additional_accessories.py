"""Iter 234 — GDG-2 toggle + Aksesoris kurang di permintaan ADDITIONAL.

Test dijalankan berurutan (pakai `-p no:randomly`).
Semua dokumen uji diberi notes 'UJI-TA2'.
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API = f"{BASE_URL}/api"

# Ref data (data go-live klien)
VENDOR_ID = "73a9501a-9442-4aea-9367-26b36f709b54"          # pak aan
MODEL_ID = "c1f4ddbb-f7cb-44e1-a93d-65ddac862e40"           # DA-2101 Aisar
SIZE_ID = "1277a155-588e-4d71-96d1-a27bcde773be"            # ALLSIZE
SKU = "DA-2101-MHG-ALLSIZE"
KARANTINA_LOC_ID = "f268207d-7a09-4ce8-8fca-3e66d4f974ec"   # GD-L1-QC
NOTE_TAG = "UJI-TA2"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "admin@garment.com", "password": "Admin@123"},
                      timeout=30)
    assert r.status_code == 200, f"login gagal: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


STATE: dict = {
    "poA_id": None, "jobA_id": None, "jobA_item_id": None, "miA_id": None,
    "poB_id": None, "shipB_id": None, "shipB_item_id": None, "inspB_id": None,
    "reqB_id": None, "childB_id": None,
    "poC_id": None, "shipC_id": None, "shipC_item_id": None, "inspC_id": None,
    "reqC_id": None, "childC_id": None,
}


# ═══════════════════════════════════════════════════════════
# A. Config default + alur GDG-2
# ═══════════════════════════════════════════════════════════
def test_A01_config_default_false(H):
    r = requests.get(
        f"{API}/dewi/system/config/production_require_material_issued",
        headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("category") == "production"
    assert d.get("data_type") == "boolean"
    assert d.get("value") is False, f"harus OFF di awal, dapat {d.get('value')}"


def test_A02_create_po_internal_confirmed(H):
    body = {
        "business_type": "internal",
        "status": "Confirmed",
        "vendor_id": VENDOR_ID,
        "customer_name": "Uji GDG-2",
        "notes": NOTE_TAG,
        "po_date": "2026-09-24",
        "deadline": "2026-10-05",
        "items": [{
            "model_id": MODEL_ID, "size_id": SIZE_ID, "sku": SKU,
            "qty": 3, "serial_number": "SN-UJI-TA2-A",
        }],
    }
    r = requests.post(f"{API}/production-pos", json=body, headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    d = r.json()
    STATE["poA_id"] = d.get("id") or (d.get("po") or {}).get("id")
    assert STATE["poA_id"], d


def test_A03_create_job_and_mi_draft_autofilled(H):
    """POST /production-jobs {po_id} → 201; MI draft auto-created dengan
    items.location_id semua terisi dan tidak ada yang menunjuk karantina."""
    r = requests.post(f"{API}/production-jobs",
                      json={"po_id": STATE["poA_id"], "notes": NOTE_TAG},
                      headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    d = r.json()
    STATE["jobA_id"] = d["id"]
    items = d.get("items") or []
    assert items, d
    STATE["jobA_item_id"] = items[0]["id"]

    mi = d.get("material_issue_draft") or {}
    assert isinstance(mi, dict) and mi.get("id"), f"MI draft tidak dibuat: {mi}"
    STATE["miA_id"] = mi["id"]
    assert mi.get("status") == "draft"
    mi_items = mi.get("items") or []
    assert mi_items, f"MI items kosong: {mi}"
    # SEMUA baris punya location_id
    empty = [it for it in mi_items if not it.get("location_id")]
    assert not empty, f"Ada baris MI TANPA location_id: {empty}"
    # TIDAK ADA yang menunjuk lokasi karantina
    quarantined = [it for it in mi_items if it.get("location_id") == KARANTINA_LOC_ID]
    assert not quarantined, f"Ada baris MI menunjuk lokasi karantina: {quarantined}"


def test_A04_progress_ok_when_toggle_off(H):
    body = {
        "job_item_id": STATE["jobA_item_id"],
        "progress_date": "2026-09-24",
        "completed_quantity": 1,
        "notes": NOTE_TAG,
    }
    r = requests.post(f"{API}/production-progress", json=body, headers=H, timeout=30)
    assert r.status_code == 201, f"progress gagal saat toggle OFF: {r.status_code} {r.text}"


def test_A05_toggle_on_blocks_progress(H):
    r = requests.put(
        f"{API}/dewi/system/config/production_require_material_issued",
        json={"value": True}, headers=H, timeout=30)
    assert r.status_code == 200, r.text

    body = {
        "job_item_id": STATE["jobA_item_id"],
        "progress_date": "2026-09-24",
        "completed_quantity": 1,
        "notes": NOTE_TAG,
    }
    r = requests.post(f"{API}/production-progress", json=body, headers=H, timeout=30)
    assert r.status_code == 400, f"harus 400 GDG-2: {r.status_code} {r.text}"
    assert "GDG-2" in r.text or "Material" in r.text


def test_A06_submit_and_approve_mi(H):
    # Submit
    r = requests.post(f"{API}/rahaza/material-issues/{STATE['miA_id']}/submit",
                      headers=H, timeout=60)
    assert r.status_code == 200, f"submit gagal: {r.status_code} {r.text}"
    d = r.json()
    assert d.get("status") == "pending_approval", d.get("status")

    # Approve (inventory_allow_negative harus TRUE agar stok kosong tetap issue)
    r = requests.post(f"{API}/rahaza/material-issues/{STATE['miA_id']}/approve",
                      headers=H, timeout=60)
    assert r.status_code == 200, f"approve gagal: {r.status_code} {r.text}"
    d = r.json()
    assert d.get("status") == "issued", d.get("status")


def test_A07_progress_ok_after_issued(H):
    body = {
        "job_item_id": STATE["jobA_item_id"],
        "progress_date": "2026-09-24",
        "completed_quantity": 1,
        "notes": NOTE_TAG,
    }
    r = requests.post(f"{API}/production-progress", json=body, headers=H, timeout=30)
    assert r.status_code == 201, f"progress harusnya lulus setelah issued: {r.status_code} {r.text}"


def test_A08_revert_config_to_false(H):
    r = requests.put(
        f"{API}/dewi/system/config/production_require_material_issued",
        json={"value": False}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    v = requests.get(
        f"{API}/dewi/system/config/production_require_material_issued",
        headers=H, timeout=30).json().get("value")
    assert v is False


# ═══════════════════════════════════════════════════════════
# B. Aksesoris kurang di permintaan ADDITIONAL
# ═══════════════════════════════════════════════════════════
def test_B01_create_po_internal_for_accessory_flow(H):
    body = {
        "business_type": "internal",
        "status": "Confirmed",
        "vendor_id": VENDOR_ID,
        "customer_name": "Uji ACC-Kurang",
        "notes": NOTE_TAG,
        "po_date": "2026-09-24",
        "deadline": "2026-10-05",
        "items": [{
            "model_id": MODEL_ID, "size_id": SIZE_ID, "sku": SKU,
            "qty": 10, "serial_number": "SN-UJI-TA2-B",
        }],
    }
    r = requests.post(f"{API}/production-pos", json=body, headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    STATE["poB_id"] = r.json().get("id")

    # Verifikasi po_accessories terbentuk (dari BOM DA-2101)
    detail = requests.get(f"{API}/production-pos/{STATE['poB_id']}",
                          headers=H, timeout=30).json()
    accs = detail.get("po_accessories") or []
    assert len(accs) >= 2, f"po_accessories kurang: {accs}"


def test_B02_create_vendor_shipment(H):
    body = {
        "vendor_id": VENDOR_ID,
        "po_id": STATE["poB_id"],
        "shipment_date": "2026-09-24",
        "notes": NOTE_TAG,
        "items": [{
            "po_item_id": None,  # akan di-resolve backend via po_id + sku
            "sku": SKU, "size": "ALLSIZE", "color": "MHG",
            "serial_number": "SN-UJI-TA2-B",
            "qty_sent": 10,
        }],
    }
    # perlu po_item_id — ambil dari detail
    detail = requests.get(f"{API}/production-pos/{STATE['poB_id']}",
                          headers=H, timeout=30).json()
    po_items = detail.get("items") or detail.get("po_items") or []
    assert po_items
    body["items"][0]["po_item_id"] = po_items[0]["id"]

    r = requests.post(f"{API}/vendor-shipments", json=body, headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    d = r.json()
    STATE["shipB_id"] = d.get("id") or (d.get("shipment") or {}).get("id")
    assert STATE["shipB_id"], d


def test_B03_receive_shipment(H):
    r = requests.put(f"{API}/vendor-shipments/{STATE['shipB_id']}",
                     json={"status": "Received", "vendor_id": VENDOR_ID},
                     headers=H, timeout=30)
    assert r.status_code == 200, r.text


def test_B04_inspect_with_shortage(H):
    detail = requests.get(f"{API}/vendor-shipments/{STATE['shipB_id']}",
                          headers=H, timeout=30).json()
    ship_items = detail.get("items") or []
    assert ship_items
    STATE["shipB_item_id"] = ship_items[0]["id"]
    po_accs = detail.get("po_accessories") or []
    assert len(po_accs) >= 2, f"po_accessories tidak muncul di GET shipment: {po_accs}"

    acc_items = [{
        "accessory_id": po_accs[0].get("accessory_id") or po_accs[0].get("id"),
        "accessory_code": po_accs[0].get("accessory_code", ""),
        "accessory_name": po_accs[0].get("accessory_name", ""),
        "unit": po_accs[0].get("unit", "pcs"),
        "ordered_qty": 10, "received_qty": 7, "missing_qty": 3,
    }, {
        "accessory_id": po_accs[1].get("accessory_id") or po_accs[1].get("id"),
        "accessory_code": po_accs[1].get("accessory_code", ""),
        "accessory_name": po_accs[1].get("accessory_name", ""),
        "unit": po_accs[1].get("unit", "pcs"),
        "ordered_qty": 10, "received_qty": 7, "missing_qty": 3,
    }]

    body = {
        "shipment_id": STATE["shipB_id"],
        "vendor_id": VENDOR_ID,
        "inspection_date": "2026-09-24",
        "overall_notes": NOTE_TAG,
        "items": [{
            "shipment_item_id": STATE["shipB_item_id"],
            "po_item_id": ship_items[0].get("po_item_id"),
            "sku": SKU, "product_name": ship_items[0].get("product_name", ""),
            "size": "ALLSIZE", "color": "MHG",
            "ordered_qty": 10, "received_qty": 8, "missing_qty": 2,
        }],
        "accessory_items": acc_items,
    }
    r = requests.post(f"{API}/vendor-material-inspections", json=body,
                      headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    STATE["inspB_id"] = r.json().get("id")


def test_B05_create_material_request_additional(H):
    detail = requests.get(f"{API}/vendor-shipments/{STATE['shipB_id']}",
                          headers=H, timeout=30).json()
    ship_items = detail.get("items") or []
    body = {
        "vendor_id": VENDOR_ID,
        "request_type": "ADDITIONAL",
        "original_shipment_id": STATE["shipB_id"],
        "po_id": STATE["poB_id"],
        "reason": NOTE_TAG + " kurang 2 pcs",
        "inspection_id": STATE["inspB_id"],
        "items": [{
            "shipment_item_id": STATE["shipB_item_id"],
            "po_item_id": ship_items[0].get("po_item_id"),
            "sku": SKU, "product_name": ship_items[0].get("product_name", ""),
            "requested_qty": 2,
        }],
    }
    r = requests.post(f"{API}/material-requests", json=body, headers=H, timeout=60)
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    STATE["reqB_id"] = r.json().get("id")


def test_B06_list_additional_carries_accessory_shortages(H):
    r = requests.get(f"{API}/material-requests?request_type=ADDITIONAL",
                     headers=H, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    docs = data if isinstance(data, list) else data.get("data") or data.get("items") or []
    ours = [d for d in docs if d.get("id") == STATE["reqB_id"]]
    assert ours, f"permintaan tidak ditemukan di list: {STATE['reqB_id']}"
    accs = ours[0].get("accessory_shortages") or []
    assert len(accs) == 2, f"accessory_shortages harus 2 baris, dapat: {accs}"
    for a in accs:
        assert int(a.get("missing_qty", 0)) == 3, f"missing_qty harus 3: {a}"


def test_B07_approve_with_custom_accessory_qty(H):
    # Ubah qty aksesoris via body: baris pertama 2, baris kedua 3
    r_list = requests.get(f"{API}/material-requests?request_type=ADDITIONAL",
                          headers=H, timeout=30).json()
    docs = r_list if isinstance(r_list, list) else r_list.get("data") or []
    ours = [d for d in docs if d.get("id") == STATE["reqB_id"]][0]
    accs = ours["accessory_shortages"]

    body = {
        "status": "Approved",
        "admin_notes": "ok " + NOTE_TAG,
        "accessory_items": [
            {**accs[0], "qty_sent": 2},
            {**accs[1], "qty_sent": 3},
        ],
    }
    r = requests.put(f"{API}/material-requests/{STATE['reqB_id']}",
                     json=body, headers=H, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    d = r.json()
    child = d.get("child_shipment") or {}
    STATE["childB_id"] = child.get("id") or d.get("child_shipment_id")
    assert STATE["childB_id"], d
    acc_sent = child.get("accessory_items") or []
    assert len(acc_sent) == 2, f"child accessory_items harus 2: {acc_sent}"
    qtys = sorted([int(a.get("qty_sent", 0)) for a in acc_sent])
    assert qtys == [2, 3], f"qty harus [2,3], dapat: {qtys}"


def test_B08_child_shipment_has_accessories_in_get(H):
    r = requests.get(f"{API}/vendor-shipments/{STATE['childB_id']}",
                     headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    accs = d.get("accessory_items") or []
    assert len(accs) == 2, f"GET child shipment accessory_items harus 2: {accs}"
    qtys = sorted([int(a.get("qty_sent", 0)) for a in accs])
    assert qtys == [2, 3], qtys


def test_B09_component_requests_fulfilled(H):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _q():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        docs = await db.dewi_cmt_component_requests.find(
            {"inspection_id": STATE["inspB_id"]}, {"_id": 0}).to_list(None)
        cli.close()
        return docs
    docs = asyncio.run(_q())
    assert docs, f"component_requests tidak ada untuk inspection_id {STATE['inspB_id']}"
    # Setidaknya ada satu berstatus fulfilled (aksesoris)
    fulfilled = [d for d in docs if d.get("status") == "fulfilled"]
    assert fulfilled, f"tidak ada component_request 'fulfilled': {[(d.get('component_type'), d.get('status')) for d in docs]}"


# ═══════════════════════════════════════════════════════════
# C. Approve TANPA accessory_items → child membawa semua kekurangan otomatis
# ═══════════════════════════════════════════════════════════
def test_C01_flow_without_accessory_items_in_body(H):
    # PO baru
    body = {
        "business_type": "internal", "status": "Confirmed",
        "vendor_id": VENDOR_ID, "customer_name": "Uji ACC-Auto",
        "notes": NOTE_TAG, "po_date": "2026-09-24", "deadline": "2026-10-05",
        "items": [{"model_id": MODEL_ID, "size_id": SIZE_ID, "sku": SKU,
                   "qty": 10, "serial_number": "SN-UJI-TA2-C"}],
    }
    r = requests.post(f"{API}/production-pos", json=body, headers=H, timeout=60)
    assert r.status_code == 201, r.text
    STATE["poC_id"] = r.json().get("id")

    detail = requests.get(f"{API}/production-pos/{STATE['poC_id']}",
                          headers=H, timeout=30).json()
    po_item_id = (detail.get("items") or detail.get("po_items"))[0]["id"]

    # Shipment
    r = requests.post(f"{API}/vendor-shipments",
                      json={"vendor_id": VENDOR_ID, "po_id": STATE["poC_id"],
                            "shipment_date": "2026-09-24", "notes": NOTE_TAG,
                            "items": [{"po_item_id": po_item_id, "sku": SKU,
                                       "size": "ALLSIZE", "color": "MHG",
                                       "serial_number": "SN-UJI-TA2-C",
                                       "qty_sent": 10}]},
                      headers=H, timeout=60)
    assert r.status_code == 201, r.text
    STATE["shipC_id"] = r.json().get("id")

    r = requests.put(f"{API}/vendor-shipments/{STATE['shipC_id']}",
                     json={"status": "Received", "vendor_id": VENDOR_ID},
                     headers=H, timeout=30)
    assert r.status_code == 200, r.text

    detail = requests.get(f"{API}/vendor-shipments/{STATE['shipC_id']}",
                          headers=H, timeout=30).json()
    ship_items = detail.get("items") or []
    STATE["shipC_item_id"] = ship_items[0]["id"]
    po_accs = detail.get("po_accessories") or []

    r = requests.post(f"{API}/vendor-material-inspections",
                      json={"shipment_id": STATE["shipC_id"], "vendor_id": VENDOR_ID,
                            "inspection_date": "2026-09-24", "overall_notes": NOTE_TAG,
                            "items": [{"shipment_item_id": STATE["shipC_item_id"],
                                       "po_item_id": ship_items[0].get("po_item_id"),
                                       "sku": SKU, "size": "ALLSIZE", "color": "MHG",
                                       "ordered_qty": 10, "received_qty": 8, "missing_qty": 2}],
                            "accessory_items": [{
                                "accessory_id": po_accs[0].get("accessory_id") or po_accs[0].get("id"),
                                "accessory_code": po_accs[0].get("accessory_code", ""),
                                "accessory_name": po_accs[0].get("accessory_name", ""),
                                "unit": po_accs[0].get("unit", "pcs"),
                                "ordered_qty": 10, "received_qty": 6, "missing_qty": 4,
                            }]},
                      headers=H, timeout=60)
    assert r.status_code == 201, r.text
    STATE["inspC_id"] = r.json().get("id")

    r = requests.post(f"{API}/material-requests",
                      json={"vendor_id": VENDOR_ID, "request_type": "ADDITIONAL",
                            "original_shipment_id": STATE["shipC_id"],
                            "po_id": STATE["poC_id"], "reason": NOTE_TAG,
                            "inspection_id": STATE["inspC_id"],
                            "items": [{"shipment_item_id": STATE["shipC_item_id"],
                                       "po_item_id": ship_items[0].get("po_item_id"),
                                       "sku": SKU,
                                       "product_name": ship_items[0].get("product_name", ""),
                                       "requested_qty": 2}]},
                      headers=H, timeout=60)
    assert r.status_code == 201, r.text
    STATE["reqC_id"] = r.json().get("id")

    # Approve TANPA field accessory_items → harus membawa semua kekurangan otomatis (missing_qty=4)
    r = requests.put(f"{API}/material-requests/{STATE['reqC_id']}",
                     json={"status": "Approved", "admin_notes": "auto " + NOTE_TAG},
                     headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    child = d.get("child_shipment") or {}
    STATE["childC_id"] = child.get("id") or d.get("child_shipment_id")
    accs = child.get("accessory_items") or []
    assert len(accs) == 1, f"child harus bawa 1 aksesoris (auto): {accs}"
    assert int(accs[0].get("qty_sent", 0)) == 4, f"qty auto harus 4 (missing): {accs}"


# ═══════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════
def test_zzz_cleanup(H):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    # DELETE via API (child dulu, lalu induk)
    for cid in [STATE.get("childB_id"), STATE.get("childC_id")]:
        if cid:
            try:
                requests.delete(f"{API}/vendor-shipments/{cid}",
                                headers=H, timeout=30)
            except Exception:
                pass
    for sid in [STATE.get("shipB_id"), STATE.get("shipC_id")]:
        if sid:
            try:
                requests.delete(f"{API}/vendor-shipments/{sid}",
                                headers=H, timeout=30)
            except Exception:
                pass
    for jid in [STATE.get("jobA_id")]:
        if jid:
            try:
                requests.delete(f"{API}/production-jobs/{jid}",
                                headers=H, timeout=30)
            except Exception:
                pass
    for pid in [STATE.get("poA_id"), STATE.get("poB_id"), STATE.get("poC_id")]:
        if pid:
            try:
                requests.delete(f"{API}/production-pos/{pid}",
                                headers=H, timeout=30)
            except Exception:
                pass

    async def _clean():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]

        req_ids = [x for x in [STATE.get("reqB_id"), STATE.get("reqC_id")] if x]
        if req_ids:
            await db.material_requests.delete_many({"id": {"$in": req_ids}})

        insp_ids = [x for x in [STATE.get("inspB_id"), STATE.get("inspC_id")] if x]
        if insp_ids:
            await db.vendor_material_inspection_items.delete_many(
                {"inspection_id": {"$in": insp_ids}})
            await db.vendor_material_inspections.delete_many({"id": {"$in": insp_ids}})
            await db.dewi_cmt_component_requests.delete_many(
                {"inspection_id": {"$in": insp_ids}})

        ship_ids = [x for x in [STATE.get("shipB_id"), STATE.get("shipC_id"),
                                STATE.get("childB_id"), STATE.get("childC_id")] if x]
        if ship_ids:
            await db.accessory_shipment_items.delete_many(
                {"shipment_id": {"$in": ship_ids}})
            await db.vendor_shipment_items.delete_many({"shipment_id": {"$in": ship_ids}})
            await db.vendor_shipments.delete_many({"id": {"$in": ship_ids}})

        # MI uji (termasuk auto-issue "Kirim Material CMT" dari shipment uji)
        mi_docs = await db.rahaza_material_issues.find(
            {"$or": [{"notes": {"$regex": NOTE_TAG}},
                     {"notes": {"$regex": "^Otomatis dari Kirim Material CMT SHP-202609-"}},
                     {"job_id": STATE.get("jobA_id")}]},
            {"id": 1, "_id": 0}).to_list(None)
        mi_ids = [m["id"] for m in mi_docs]
        if mi_ids:
            await db.rahaza_stock_ledger.delete_many({"ref.ref_id": {"$in": mi_ids}})
            await db.rahaza_material_movements.delete_many({"ref_id": {"$in": mi_ids}})
            src_refs = [f"mi:{mid}" for mid in mi_ids]
            je = await db.rahaza_journal_entries.find(
                {"source_ref": {"$in": src_refs}}, {"id": 1, "_id": 0}).to_list(None)
            je_ids = [j["id"] for j in je]
            if je_ids:
                await db.rahaza_journal_lines.delete_many({"journal_id": {"$in": je_ids}})
                await db.rahaza_journal_entries.delete_many({"id": {"$in": je_ids}})
            await db.rahaza_material_issues.delete_many({"id": {"$in": mi_ids}})

        # baris stok minus uji
        await db.rahaza_material_stock.delete_many({"qty": {"$lt": 0}})

        # progress uji
        await db.production_progress.delete_many({"notes": {"$regex": NOTE_TAG}})

        # job items yatim (defensif)
        if STATE.get("jobA_id"):
            await db.production_job_items.delete_many({"job_id": STATE["jobA_id"]})
            await db.production_jobs.delete_many({"id": STATE["jobA_id"]})

        # counters (bila koleksi kosong dari prefix uji)
        if not await db.vendor_shipments.count_documents(
                {"shipment_number": {"$regex": "^SHP-202609-"}}):
            await db.counters.delete_many({"_id": {"$regex": "^SHP-202609-"}})
        if not await db.production_pos.count_documents(
                {"po_number": {"$regex": "^PO-INT-202609-"}}):
            await db.counters.delete_many({"_id": {"$regex": "^PO-INT-202609-"}})
        if not await db.rahaza_material_issues.count_documents({}):
            await db.counters.delete_many({"_id": {"$regex": "^MI-2026"}})

        cli.close()

    asyncio.run(_clean())

    # Sanity: setelan production_require_material_issued OFF + inventory_allow_negative ON
    v1 = requests.get(
        f"{API}/dewi/system/config/production_require_material_issued",
        headers=H, timeout=30).json().get("value")
    v2 = requests.get(
        f"{API}/dewi/system/config/inventory_allow_negative",
        headers=H, timeout=30).json().get("value")
    assert v1 is False, f"production_require_material_issued harus OFF di akhir: {v1}"
    assert v2 is True, f"inventory_allow_negative harus ON di akhir: {v2}"
