"""Iter215 — Validate BOM_AKSESORIS golive file: preview totals, apply idempotency (scope=bom),
laporan-sisa 10 sheets, gap-workbook has BOM_AKSESORIS sheet, DB models count and DA-1101 BOM.
Read-only / idempotent tests (no seed reset)."""
import io
import os
import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
FILE_PATH = "/app/private/golive/DATA_YANG_PERLU_DIISI_DA_2.xlsx"
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in {r.json()}"
    return tok


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def file_bytes():
    with open(FILE_PATH, "rb") as f:
        return f.read()


def _upload(url, hdr, file_bytes):
    files = {"file": ("DATA.xlsx", io.BytesIO(file_bytes),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    return requests.post(url, headers=hdr, files=files, timeout=180)


# ---------------- preview ----------------
def test_fill_preview_totals_and_issues(hdr, file_bytes):
    r = _upload(f"{BASE_URL}/api/rahaza/master/fill-preview", hdr, file_bytes)
    assert r.status_code == 200, f"preview status {r.status_code} {r.text[:500]}"
    j = r.json()
    assert j.get("ok") is True, f"ok flag={j.get('ok')} errors={j.get('errors')}"
    totals = j.get("totals", {})
    assert totals.get("bom_lines") == 137, f"bom_lines={totals.get('bom_lines')}"
    assert totals.get("bom_groups") == 72, f"bom_groups={totals.get('bom_groups')}"
    assert totals.get("bom_models") == 45, f"bom_models={totals.get('bom_models')}"
    assert totals.get("bom_models_in_file") == 104, f"bom_models_in_file={totals.get('bom_models_in_file')}"
    ic = j.get("bom_issue_counts", {})
    expected_ic = {
        "satuan_tak_valid": 466,
        "qty_kosong": 4,
        "model_tanpa_sku": 47,
        "warna_tak_dikenal": 2,
        "kelompok_tanpa_varian": 103,
    }
    for k, v in expected_ic.items():
        assert ic.get(k) == v, f"issue_count {k}={ic.get(k)} expected {v} full={ic}"


# ---------------- apply idempotent ----------------
def test_fill_apply_scope_bom_idempotent(hdr, file_bytes):
    r = _upload(f"{BASE_URL}/api/rahaza/master/fill-apply?scope=bom", hdr, file_bytes)
    assert r.status_code == 200, f"apply status {r.status_code} {r.text[:500]}"
    j = r.json()
    assert j.get("scope") == "bom", f"scope={j.get('scope')}"
    expected = {
        "boms_unchanged": 408,
        "bom_lines_appended": 0,
        "bom_lines_replaced": 0,
        "bom_base_created": 0,
        "sku_prices_updated": 0,
        "materials_updated": 0,
    }
    for k, v in expected.items():
        assert j.get(k) == v, f"apply.{k}={j.get(k)} expected {v} full={j}"


# ---------------- laporan-sisa ----------------
def test_laporan_sisa_10_sheets(hdr, file_bytes):
    r = _upload(f"{BASE_URL}/api/rahaza/master/laporan-sisa", hdr, file_bytes)
    assert r.status_code == 200, f"laporan status {r.status_code} {r.text[:500]}"
    wb = load_workbook(io.BytesIO(r.content), read_only=True)
    names = wb.sheetnames
    expected_sheets = [
        "RINGKASAN",
        "1_MODEL_TANPA_SKU",
        "VARIAN_BARU",
        "2_KELOMPOK_TANPA_VARIAN",
        "3_SATUAN_KODE_TAK_VALID",
        "4_WARNA_TAK_DIKENAL",
        "5_MATERIAL_HARGA_0",
        "6_HARGA_JUAL_SKU",
        "7_LAINNYA",
        "8_HPP_BELUM_TERVALIDASI",
    ]
    for s in expected_sheets:
        assert s in names, f"sheet {s} missing; got {names}"
    # row counts (data rows = max_row - 1 header)
    expected_rows = {
        "1_MODEL_TANPA_SKU": 20,
        "VARIAN_BARU": 38,
        "2_KELOMPOK_TANPA_VARIAN": 103,
        "3_SATUAN_KODE_TAK_VALID": 470,
        "4_WARNA_TAK_DIKENAL": 2,
        "5_MATERIAL_HARGA_0": 87,
        "6_HARGA_JUAL_SKU": 62,
        "7_LAINNYA": 131,
        "8_HPP_BELUM_TERVALIDASI": 75,
    }
    mismatches = {}
    for s, exp in expected_rows.items():
        ws = wb[s]
        got = ws.max_row - 1 if ws.max_row else 0
        if got != exp:
            mismatches[s] = f"got={got} exp={exp}"
    assert not mismatches, f"row-count mismatch: {mismatches}"


# ---------------- gap workbook ----------------
def test_gap_workbook_has_bom_sheet(hdr):
    r = requests.get(f"{BASE_URL}/api/rahaza/master/gap-workbook", headers=hdr, timeout=60)
    assert r.status_code == 200, f"gap status {r.status_code}"
    wb = load_workbook(io.BytesIO(r.content), read_only=True)
    assert "BOM_AKSESORIS" in wb.sheetnames, f"no BOM_AKSESORIS in {wb.sheetnames}"


# ---------------- DB state via API ----------------
def test_models_count_and_da1101_bom(hdr):
    # Try several likely list endpoints
    r = requests.get(f"{BASE_URL}/api/rahaza/models", headers=hdr, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"/api/rahaza/models not available: {r.status_code}")
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert isinstance(items, list), f"unexpected shape {type(items)}"
    assert len(items) == 104, f"models count={len(items)}"

    # DA-1101: locate model UUID by code
    da1101 = next((m for m in items if (m.get("code") or m.get("model_code")) == "DA-1101"), None)
    assert da1101, "DA-1101 not found in models list"
    mid = da1101.get("id") or da1101.get("_id")
    assert mid, f"no id in DA-1101 doc: {list(da1101.keys())}"

    r2 = requests.get(f"{BASE_URL}/api/rahaza/models/{mid}/bom", headers=hdr, timeout=60)
    assert r2.status_code == 200, f"DA-1101 bom fetch status {r2.status_code} {r2.text[:300]}"
    payload = r2.json()
    matrix = payload.get("matrix", [])
    # Find HTM or MHG variant with a bom_id
    target = next((b for b in matrix if b.get("color_code") in ("HTM", "MHG") and b.get("bom_id")), None)
    assert target, f"no HTM/MHG BOM row for DA-1101; colors={[m.get('color_code') for m in matrix]}"
    bid = target["bom_id"]
    r3 = requests.get(f"{BASE_URL}/api/rahaza/boms/{bid}", headers=hdr, timeout=60)
    assert r3.status_code == 200, f"bom detail {r3.status_code}"
    bom_txt = str(r3.json())
    assert "A-KRT-0003" in bom_txt, f"A-KRT-0003 not in DA-1101 {target['color_code']} BOM"
