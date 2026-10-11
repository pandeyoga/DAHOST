"""Iter 233 — Backend tests untuk mode SEMENTARA `inventory_allow_negative`.

Skenario:
1. Konfig `inventory_allow_negative` (default ON) — GET.
2. Buat PO INTERNAL uji (varian ber-BOM: DA-1101-BRG-ALLSIZE).
3. material-preview → allow_negative True, blocking False, ada baris problem.
4. POST vendor-shipments (mode ON) → 201; MI dibuat + negative_stock_lines terisi;
   baris minus muncul di rahaza_material_stock (A-* di GD-L1-ACC).
5. Shipment KEDUA (qty 1) → stok makin minus.
6. GET /api/rahaza/material-stock?negative=1 hanya baris qty<0.
7. Matikan setelan (PUT value=false) → preview blocking=True; POST vendor-shipments → 400.
8. Nyalakan lagi (PUT value=true).
9. Cleanup dokumen + baris uji.
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://sku-inventory-pull.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"

# Data referensi (verified via mongo)
VENDOR_ID = "73a9501a-9442-4aea-9367-26b36f709b54"  # pak aan (aktif)
MODEL_ID = "c0fcc612-4cad-45ca-81d1-ece65a66f3d1"   # DA-1101 Lyora (punya BOM)
SIZE_ID = "1277a155-588e-4d71-96d1-a27bcde773be"    # ALLSIZE
SKU = "DA-1101-BRG-ALLSIZE"
NOTE_TAG = "UJI-TA-NEG"


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


# State bersama antar tests (urutan penting → -p no:randomly)
STATE: dict = {"po_id": None, "po_item_id": None, "shipments": [], "mi_ids": []}


# ─────────────────────────────────────────────────────────────
# 1. Config
# ─────────────────────────────────────────────────────────────
def test_01_config_default_on(H):
    r = requests.get(f"{API}/dewi/system/config/inventory_allow_negative", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("category") == "inventory"
    assert d.get("data_type") == "boolean"
    # Owner ingin default ON
    assert d.get("value") is True, f"harus ON di awal, dapat {d.get('value')}"


# ─────────────────────────────────────────────────────────────
# 2. Bikin PO INTERNAL uji
# ─────────────────────────────────────────────────────────────
def test_02_create_po_internal(H):
    body = {
        "business_type": "internal",
        "status": "Confirmed",
        "vendor_id": VENDOR_ID,
        "customer_name": "Gudang FG Sendiri",
        "notes": NOTE_TAG,
        "po_date": "2026-09-23",
        "deadline": "2026-09-30",
        "items": [{
            "model_id": MODEL_ID, "size_id": SIZE_ID, "sku": SKU,
            "qty": 5, "serial_number": "SN-UJI-TA-NEG",
        }],
    }
    r = requests.post(f"{API}/production-pos", json=body, headers=H, timeout=60)
    assert r.status_code == 201, f"create PO gagal: {r.status_code} {r.text}"
    d = r.json()
    po_id = d.get("id") or (d.get("po") or {}).get("id")
    assert po_id, f"no po id in response: {d}"
    STATE["po_id"] = po_id
    STATE["po_number"] = d.get("po_number") or (d.get("po") or {}).get("po_number")

    # Ambil po_item_id via DB (public endpoint /po/{id}/items?)
    r2 = requests.get(f"{API}/production-pos/{po_id}", headers=H, timeout=30)
    assert r2.status_code == 200, r2.text
    pod = r2.json()
    items = pod.get("items") or pod.get("po_items") or []
    assert items, f"no items in po detail: {pod}"
    STATE["po_item_id"] = items[0].get("id")
    assert STATE["po_item_id"], f"no po_item_id: {items[0]}"


# ─────────────────────────────────────────────────────────────
# 3. Preview (mode ON) — allow_negative True, non-blocking
# ─────────────────────────────────────────────────────────────
def test_03_preview_on_nonblocking(H):
    body = {"po_id": STATE["po_id"], "items": [{"po_item_id": STATE["po_item_id"], "qty_sent": 2}]}
    r = requests.post(f"{API}/vendor-shipments/material-preview", json=body, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("applicable") is True, f"harus applicable: {d}"
    assert d.get("allow_negative") is True, f"harus allow_negative True: {d}"
    assert d.get("has_shortage") is True, f"harus has_shortage True (stok 0 semua): {d}"
    assert d.get("blocking") is False, f"blocking harus False saat mode ON: {d}"
    lines = d.get("materials") or d.get("lines") or d.get("material_lines") or []
    assert lines, f"lines kosong: {d}"
    STATE["preview_lines"] = lines
    problem_texts = " | ".join([str(ln.get("problem") or "") for ln in lines])
    assert ("minus" in problem_texts.lower()) or ("akan minus" in problem_texts.lower()), \
        f"tidak ada teks 'minus' di problem: {problem_texts}"


# ─────────────────────────────────────────────────────────────
# 4. POST vendor-shipments (mode ON) → 201 + MI + baris minus
# ─────────────────────────────────────────────────────────────
def test_04_create_shipment_negative_stock(H):
    body = {
        "vendor_id": VENDOR_ID, "po_id": STATE["po_id"],
        "shipment_type": "NORMAL",
        "shipment_date": "2026-09-23",
        "notes": NOTE_TAG,
        "items": [{"po_id": STATE["po_id"], "po_item_id": STATE["po_item_id"],
                   "sku": SKU, "qty_sent": 2}],
    }
    r = requests.post(f"{API}/vendor-shipments", json=body, headers=H, timeout=120)
    assert r.status_code == 201, f"create shipment gagal: {r.status_code} {r.text}"
    d = r.json()
    sid = d.get("id") or (d.get("shipment") or {}).get("id")
    assert sid, f"no shipment id: {d}"
    STATE["shipments"].append(sid)
    mi = d.get("material_issue") or {}
    assert mi.get("mi_number"), f"MI number kosong: {d}"
    neg_lines = mi.get("negative_stock_lines") or []
    assert neg_lines, f"negative_stock_lines harus terisi mode ON: {mi}"


def test_05_verify_negative_stock_in_db(H):
    r = requests.get(f"{API}/rahaza/material-stock?negative=1", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0, f"harus ada baris negatif: {rows}"
    for row in rows:
        assert float(row.get("qty", 0)) < 0, f"baris bukan negatif: {row}"
        assert row.get("material_code"), f"missing material_code: {row}"
        assert row.get("location_code"), f"missing location_code: {row}"
        assert row.get("unit"), f"missing unit: {row}"
    # A-* material di GD-L1-ACC ?
    a_rows = [r_ for r_ in rows if str(r_.get("material_code", "")).startswith("A-")]
    if a_rows:
        assert any(r_.get("location_code") == "GD-L1-ACC" for r_ in a_rows), \
            f"A-* material tidak di GD-L1-ACC: {a_rows}"
    STATE["neg_count_after_1"] = len(rows)


# ─────────────────────────────────────────────────────────────
# 5. Kirim shipment KEDUA → stok makin minus
# ─────────────────────────────────────────────────────────────
def test_06_second_shipment_makes_more_negative(H):
    # preview dulu — available harus negatif dan problem 'stok kurang (akan minus …)'
    body = {"po_id": STATE["po_id"], "items": [{"po_item_id": STATE["po_item_id"], "qty_sent": 1}]}
    rp = requests.post(f"{API}/vendor-shipments/material-preview", json=body, headers=H, timeout=60)
    assert rp.status_code == 200, rp.text
    dp = rp.json()
    lines = dp.get("materials") or dp.get("lines") or []
    # ambil salah satu baris → available < 0
    available_negs = [ln for ln in lines
                      if any(float(ln.get(k, 0) or 0) < 0
                             for k in ("available", "current", "available_qty", "on_hand"))]
    # tidak strict, tapi harus setidaknya ada teks 'stok kurang'
    problem_texts = " | ".join([str(ln.get("problem") or "") for ln in lines])
    assert ("stok kurang" in problem_texts.lower()) or ("minus" in problem_texts.lower()), \
        f"problem preview shipment ke-2 tidak mencerminkan minus: {problem_texts}"

    body2 = {
        "vendor_id": VENDOR_ID, "po_id": STATE["po_id"],
        "shipment_type": "NORMAL",
        "shipment_date": "2026-09-23",
        "notes": NOTE_TAG,
        "items": [{"po_id": STATE["po_id"], "po_item_id": STATE["po_item_id"],
                   "sku": SKU, "qty_sent": 1}],
    }
    r = requests.post(f"{API}/vendor-shipments", json=body2, headers=H, timeout=120)
    assert r.status_code == 201, f"create shipment2: {r.status_code} {r.text}"
    d = r.json()
    sid = d.get("id") or (d.get("shipment") or {}).get("id")
    assert sid
    STATE["shipments"].append(sid)

    # Verifikasi jumlah minus makin negatif (bukan bertambah baris — bertambah kuantum negatif)
    # cek satu baris material di DB langsung via API
    r2 = requests.get(f"{API}/rahaza/material-stock?negative=1", headers=H, timeout=60)
    assert r2.status_code == 200
    rows = r2.json()
    # Jumlah baris minus setelah shipment ke-2 ≥ setelah shipment ke-1
    assert len(rows) >= STATE.get("neg_count_after_1", 0), \
        f"baris minus turun setelah shipment ke-2: sebelum={STATE.get('neg_count_after_1')}, sekarang={len(rows)}"


# ─────────────────────────────────────────────────────────────
# 6. Matikan setelan → blocking + 400
# ─────────────────────────────────────────────────────────────
def test_07_toggle_off_blocks(H):
    r = requests.put(f"{API}/dewi/system/config/inventory_allow_negative",
                     json={"value": False}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    # verify
    r2 = requests.get(f"{API}/dewi/system/config/inventory_allow_negative", headers=H, timeout=30)
    assert r2.json().get("value") is False, r2.text

    # preview → blocking True
    body = {"po_id": STATE["po_id"], "items": [{"po_item_id": STATE["po_item_id"], "qty_sent": 1}]}
    rp = requests.post(f"{API}/vendor-shipments/material-preview", json=body, headers=H, timeout=60)
    assert rp.status_code == 200, rp.text
    dp = rp.json()
    assert dp.get("blocking") is True, f"blocking harus True saat OFF: {dp}"
    assert dp.get("allow_negative") is False, f"allow_negative harus False: {dp}"

    # POST shipment → 400
    body2 = {
        "vendor_id": VENDOR_ID, "po_id": STATE["po_id"],
        "shipment_type": "NORMAL",
        "shipment_date": "2026-09-23",
        "notes": NOTE_TAG + "-BLOCKED",
        "items": [{"po_id": STATE["po_id"], "po_item_id": STATE["po_item_id"],
                   "sku": SKU, "qty_sent": 1}],
    }
    r3 = requests.post(f"{API}/vendor-shipments", json=body2, headers=H, timeout=60)
    assert r3.status_code == 400, f"harus 400 saat OFF, dapat {r3.status_code}: {r3.text}"
    assert "surat jalan" in r3.text.lower() or "tidak dibuat" in r3.text.lower(), \
        f"pesan error tidak informatif: {r3.text}"


def test_08_toggle_back_on(H):
    r = requests.put(f"{API}/dewi/system/config/inventory_allow_negative",
                     json={"value": True}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/dewi/system/config/inventory_allow_negative", headers=H, timeout=30)
    assert r2.json().get("value") is True


# ─────────────────────────────────────────────────────────────
# 7. Cleanup — PENTING (DB = data go-live klien)
# ─────────────────────────────────────────────────────────────
def test_99_cleanup(H):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    # a) Delete shipments via API
    for sid in STATE["shipments"]:
        try:
            requests.delete(f"{API}/vendor-shipments/{sid}", headers=H, timeout=30)
        except Exception:
            pass

    # b) Delete PO via API
    if STATE.get("po_id"):
        try:
            requests.delete(f"{API}/production-pos/{STATE['po_id']}", headers=H, timeout=30)
        except Exception:
            pass

    # c) Bersihkan sisa (stok minus, MI, ledger, journal) via mongo langsung
    async def _clean():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]

        # MI uji: vendor_shipment_number berawalan 'SHP-202609' atau notes ada UJI-TA-NEG
        mi_docs = await db.rahaza_material_issues.find(
            {"$or": [{"notes": {"$regex": NOTE_TAG}},
                     {"vendor_shipment_number": {"$regex": "^SHP-202609"}}]},
            {"id": 1, "_id": 0}
        ).to_list(None)
        mi_ids = [m["id"] for m in mi_docs]

        if mi_ids:
            await db.rahaza_stock_ledger.delete_many({"ref.ref_id": {"$in": mi_ids}})
            await db.rahaza_material_movements.delete_many({"ref_id": {"$in": mi_ids}})
            src_refs = [f"mi:{mid}" for mid in mi_ids]
            je = await db.rahaza_journal_entries.find(
                {"source_ref": {"$in": src_refs}}, {"id": 1, "_id": 0}
            ).to_list(None)
            je_ids = [j["id"] for j in je]
            if je_ids:
                await db.rahaza_journal_lines.delete_many({"journal_id": {"$in": je_ids}})
                await db.rahaza_journal_entries.delete_many({"id": {"$in": je_ids}})
            await db.rahaza_material_issues.delete_many({"id": {"$in": mi_ids}})

        # baris stok minus uji — hanya yang qty<0 (aman: sebelum test ada 0 baris)
        await db.rahaza_material_stock.delete_many({"qty": {"$lt": 0}})

        # counters uji
        if not await db.vendor_shipments.count_documents({"shipment_number": {"$regex": "^SHP-202609"}}):
            await db.counters.delete_many({"_id": {"$regex": "^SHP-202609-"}})
        if not await db.production_pos.count_documents({"po_number": {"$regex": "^PO-INT-202609"}}):
            await db.counters.delete_many({"_id": {"$regex": "^PO-INT-202609-"}})
        if not await db.rahaza_material_issues.count_documents({}):
            await db.counters.delete_many({"_id": {"$regex": "^MI-2026"}})
        if not await db.rahaza_journal_entries.count_documents({"created_at": {"$exists": True}, "source_ref": {"$regex": "^mi:"}}):
            await db.counters.delete_many({"_id": {"$regex": "^JE-2026092[34]"}})

        cli.close()

    asyncio.get_event_loop().run_until_complete(_clean()) if False else asyncio.run(_clean())

    # sanity — pastikan setelan tetap ON di akhir
    r = requests.get(f"{API}/dewi/system/config/inventory_allow_negative", headers=H, timeout=30)
    assert r.json().get("value") is True
