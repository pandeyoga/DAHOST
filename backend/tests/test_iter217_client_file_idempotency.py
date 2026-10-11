"""Iter217 — Verifikasi bahwa berkas klien DATA_YANG_PERLU_DIISI_DA_2.xlsx sudah diterapkan sepenuhnya
ke DB (semua totals=0 pada preview & apply), fitur deaktivasi SKU end-to-end pada uji_harga_nonaktif.xlsx,
verifikasi state DB, dan gap-workbook (POST+GET)."""
import os, time, subprocess
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://erp-da-testing.preview.emergentagent.com").rstrip("/")
CLIENT_XLSX = "/app/private/golive/DATA_YANG_PERLU_DIISI_DA_2.xlsx"
TEST_XLSX = "/app/private/golive/uji_harga_nonaktif.xlsx"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@garment.com", "password": "Admin@123"}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


# ---------- 1) Berkas klien: preview & apply harus 0 perubahan ----------
def test_client_file_preview_zero_change(headers):
    with open(CLIENT_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/fill-preview",
                          headers=headers, files={"file": (os.path.basename(CLIENT_XLSX), f)}, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True, j
    assert j.get("errors") == [], j.get("errors")
    t = j["totals"]
    assert t["bom_lines"] == 327, t
    assert t["bom_models"] == 57, t
    assert t["sku_prices"] == 0, t
    assert t["sku_deactivate"] == 0, t
    assert t["stores"] == 0, t
    bic = j.get("bom_issue_counts", {})
    assert bic.get("model_dihentikan") == 10, bic
    assert bic.get("model_tanpa_sku") == 47, bic


def test_client_file_apply_zero_change(headers):
    with open(CLIENT_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/fill-apply?scope=all",
                          headers=headers, files={"file": (os.path.basename(CLIENT_XLSX), f)}, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("sku_prices_updated") == 0, j
    assert j.get("sku_deactivated") == 0, j
    assert j.get("stores_updated") == 0, j
    assert j.get("bom_lines_appended") == 0, j
    assert j.get("boms_unchanged") == 492, j


# ---------- 2) Verifikasi DB state pasca berkas klien ----------
def test_db_state_after_client_file(db):
    assert db.rahaza_model_variants.count_documents({"active": False}) == 30
    assert db.rahaza_materials.count_documents({"type": "fg", "active": False}) == 30
    assert db.rahaza_boms.count_documents({"active": False}) == 30

    m = db.rahaza_materials.find_one({"code": "DA-1202-CRM-M"})
    assert m and m.get("retail_price_master") == 155999, m

    for a in db.marketing_platform_accounts.find({}):
        assert a.get("coa_cash_code") == "1-1201", a
    assert db.marketing_platform_accounts.count_documents({}) == 7

    # DA-2104 varian semua nonaktif
    variants_2104 = list(db.rahaza_model_variants.find({"model_code": "DA-2104"}))
    assert len(variants_2104) == 5, len(variants_2104)
    assert all(v.get("active") is False for v in variants_2104)

    # DA-2104 hpp_validation.status='dihentikan'
    model = db.rahaza_models.find_one({"code": "DA-2104"})
    assert model and model.get("hpp_validation", {}).get("status") == "dihentikan", model


# ---------- 3) Fitur nonaktif SKU end-to-end dengan uji_harga_nonaktif.xlsx ----------
def test_deactivate_sku_preview(headers):
    with open(TEST_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/fill-preview",
                          headers=headers, files={"file": (os.path.basename(TEST_XLSX), f)}, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True
    t = j["totals"]
    assert t.get("sku_deactivate") == 1, t
    assert t.get("sku_prices") == 1, t
    assert t.get("stores") == 1, t
    lst = j.get("sku_deactivate") or []
    # sku_deactivate mungkin di field lain; cari array
    arr = j.get("sku_deactivate_items") or j.get("sku_deactivate_list") or j.get("sku_deactivates") or lst
    # inspect all top-level arrays for the sku
    found = False
    for k, v in j.items():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and item.get("sku") == "DA-1101-BRG-ALLSIZE":
                    found = True
    assert found, f"sku entry not found in response: keys={list(j.keys())}"


def test_deactivate_sku_apply(headers):
    with open(TEST_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/fill-apply?scope=all",
                          headers=headers, files={"file": (os.path.basename(TEST_XLSX), f)}, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("sku_deactivated") == 1, j
    assert j.get("sku_prices_updated") == 1, j
    assert j.get("stores_updated") == 1, j


def test_deactivate_sku_apply_idempotent(headers):
    with open(TEST_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/fill-apply?scope=all",
                          headers=headers, files={"file": (os.path.basename(TEST_XLSX), f)}, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("sku_deactivated") == 0, j
    assert j.get("sku_prices_updated") == 0, j
    assert j.get("stores_updated") == 0, j


def test_deactivate_db_verification(db):
    v = db.rahaza_model_variants.find_one({"sku": "DA-1101-BRG-ALLSIZE"})
    assert v and v.get("active") is False, v
    notes = v.get("notes") or ""
    assert "Dinonaktifkan dari Excel" in notes, notes

    fg_brg = db.rahaza_materials.find_one({"code": "DA-1101-BRG-ALLSIZE"})
    assert fg_brg and fg_brg.get("active") is False, fg_brg

    # BOM utk model_id/size_id/color_code variant BRG semua active=false
    model_id = v.get("model_id")
    size_id = v.get("size_id")
    color_code = v.get("color_code")
    q = {"model_id": model_id, "color_code": color_code}
    if size_id:
        q["size_id"] = size_id
    boms = list(db.rahaza_boms.find(q))
    assert len(boms) >= 1, q
    assert all(b.get("active") is False for b in boms), boms

    fg_crl = db.rahaza_materials.find_one({"code": "DA-1101-CRL-ALLSIZE"})
    assert fg_crl and fg_crl.get("retail_price_master") == 123456, fg_crl

    shp = db.marketing_platform_accounts.find_one({"account_code": "SHP-01"})
    assert shp and shp.get("coa_cash_code") == "1-1102", shp


def test_restart_backend_master_sync_preserves_variants(db, headers):
    before = db.rahaza_model_variants.count_documents({})
    v_before = db.rahaza_model_variants.find_one({"sku": "DA-1101-BRG-ALLSIZE"})
    assert v_before and v_before.get("active") is False

    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True, capture_output=True)
    # tunggu /api/health up
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=5)
            if r.status_code == 200 and r.json().get("db") == "connected":
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        pytest.fail("backend did not come back up")

    time.sleep(3)  # beri waktu master_sync
    after = db.rahaza_model_variants.count_documents({})
    assert after == 645, f"variants count changed {before}->{after}"
    v_after = db.rahaza_model_variants.find_one({"sku": "DA-1101-BRG-ALLSIZE"})
    assert v_after and v_after.get("active") is False


# ---------- 4) gap-workbook ----------
def test_gap_workbook_post_with_file(headers, tmp_path):
    with open(CLIENT_XLSX, "rb") as f:
        r = requests.post(f"{BASE_URL}/api/rahaza/master/gap-workbook",
                          headers=headers, files={"file": (os.path.basename(CLIENT_XLSX), f)}, timeout=180)
    assert r.status_code == 200, r.text
    cd = r.headers.get("content-disposition", "")
    assert "DATA_YANG_PERLU_DIISI_DA_SISA.xlsx" in cd, cd

    out = tmp_path / "sisa.xlsx"
    out.write_bytes(r.content)
    from openpyxl import load_workbook
    wb = load_workbook(out)
    sheets = wb.sheetnames
    assert "PETUNJUK" in sheets and "BOM_AKSESORIS" in sheets and "MODEL" in sheets and "VARIAN_BARU" in sheets, sheets

    # PETUNJUK: cek keberadaan frasa2
    petunjuk_text = "\n".join(
        " ".join(str(c) for c in row if c is not None)
        for row in wb["PETUNJUK"].iter_rows(values_only=True)
    )
    assert "DAMPAK BERKAS SEBELUMNYA" in petunjuk_text, petunjuk_text[:2000]
    assert "KEADAAN SISTEM SAAT BERKAS INI DIBUAT" in petunjuk_text, petunjuk_text[:2000]
    assert "SKU dinonaktifkan" in petunjuk_text, petunjuk_text[:2000]

    # BOM_AKSESORIS TIDAK memuat DA-2104
    bom_rows = list(wb["BOM_AKSESORIS"].iter_rows(values_only=True))
    for row in bom_rows[1:]:
        for cell in row:
            if cell and "DA-2104" in str(cell):
                pytest.fail(f"DA-2104 masih ada di BOM_AKSESORIS: {row}")

    # MODEL baris DA-2104 keterangan mengandung 'DIHENTIKAN'
    model_rows = list(wb["MODEL"].iter_rows(values_only=True))
    header = list(model_rows[0])
    # cari kolom 'keterangan' & kode/kode_model
    ket_idx = next((i for i, h in enumerate(header) if h and "keterangan" in str(h).lower()), None)
    kode_idx = next((i for i, h in enumerate(header) if h and "kode" in str(h).lower()), None)
    assert ket_idx is not None and kode_idx is not None, header
    found = False
    for row in model_rows[1:]:
        if row[kode_idx] == "DA-2104":
            found = True
            assert "DIHENTIKAN" in str(row[ket_idx]).upper(), row
    assert found, "DA-2104 not in MODEL sheet"

    # VARIAN_BARU baris data
    var_rows = list(wb["VARIAN_BARU"].iter_rows(values_only=True))
    data_rows = [r for r in var_rows[1:] if any(c is not None and str(c).strip() for c in r)]
    assert len(data_rows) == 38, len(data_rows)


def test_gap_workbook_get_no_file(headers):
    r = requests.get(f"{BASE_URL}/api/rahaza/master/gap-workbook", headers=headers, timeout=60)
    assert r.status_code == 200
    assert "DATA_YANG_PERLU_DIISI_DA.xlsx" in r.headers.get("content-disposition", "")


def test_uploads_sisa_file(headers):
    r = requests.get(f"{BASE_URL}/api/uploads/DATA_YANG_PERLU_DIISI_DA_SISA.xlsx", headers=headers, timeout=60)
    assert r.status_code == 200, r.status_code
