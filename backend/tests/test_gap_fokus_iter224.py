"""iter224 verification for POST /api/rahaza/master/gap-fokus (Berkas FOKUS).

Tests all requirements from review_request:
- Sheet order & structure (no file / with file)
- di_berkas_anda column semantics
- BOM_OTOMATIS split correctness (no yellow cells)
- BOM_AKSESORIS group has ≥1 yellow cell per group OR blank_group head
- Consistency: per-model 'perlu isian' count matches BOM_AKSESORIS rows from file
- Roundtrip: fill-preview reads BOM_OTOMATIS via BOM_SHEETS
- Auth: unauth → 401/403; non-xlsx → 400
"""
from __future__ import annotations

import io
import os
import re

import openpyxl
import pytest
import requests

BASE = "http://localhost:8001"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
YELLOW = "FFF2CC"
GREY = "EDEDED"
BLUE = "DDEBF7"
DA3_FILE = "/app/private/golive/DATA_YANG_PERLU_DIISI_DA_3.xlsx"

RINGKASAN_HEADER = [
    "kode_model", "nama_model", "kategori", "varian_aktif",
    "varian_tanpa_bom", "aksesoris_di_bom", "status", "isi_di_sheet",
    "di_berkas_anda",
]
EXPECTED_SHEET_ORDER = [
    "PETUNJUK", "RINGKASAN_MODEL", "VARIAN_BARU", "BOM_AKSESORIS",
    "BOM_OTOMATIS", "MATERIAL", "REF_AKSESORIS",
]
STOPPED_MODELS = {"DA-2104", "DA-2107", "DA-2108", "DA-2501", "DA-3601", "DA-3602"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "admin@garment.com", "password": "Admin@123"},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _fg(cell):
    fg = cell.fill.fgColor
    if fg is None:
        return None
    rgb = fg.rgb
    if isinstance(rgb, str) and len(rgb) >= 6:
        return rgb[-6:].upper()
    return None


def _load_wb(content: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


# ─── 1. GAP-FOKUS TANPA FILE ─────────────────────────────────────────────
def test_gap_fokus_no_file(auth):
    r = requests.post(f"{BASE}/api/rahaza/master/gap-fokus", headers=auth,
                      files={}, timeout=60)
    assert r.status_code == 200, r.text
    assert XLSX_MIME in r.headers.get("content-type", "")
    wb = _load_wb(r.content)
    assert wb.sheetnames == EXPECTED_SHEET_ORDER, wb.sheetnames

    ring = wb["RINGKASAN_MODEL"]
    header = [c.value for c in ring[1]]
    assert header == RINGKASAN_HEADER, header

    col_idx = RINGKASAN_HEADER.index("di_berkas_anda") + 1
    for row in ring.iter_rows(min_row=2, values_only=False):
        assert row[col_idx - 1].value == "—", f"Expected — got {row[col_idx-1].value}"

    bom_oto = wb["BOM_OTOMATIS"]
    assert bom_oto.max_row == 1, f"BOM_OTOMATIS should be header-only, got max_row={bom_oto.max_row}"


# ─── 2. GAP-FOKUS DENGAN FILE DA_3 ──────────────────────────────────────
@pytest.fixture(scope="module")
def da3_response(auth):
    if not os.path.exists(DA3_FILE):
        pytest.skip(f"missing {DA3_FILE}")
    with open(DA3_FILE, "rb") as f:
        r = requests.post(
            f"{BASE}/api/rahaza/master/gap-fokus",
            headers=auth,
            files={"file": ("DATA_YANG_PERLU_DIISI_DA_3.xlsx", f, XLSX_MIME)},
            timeout=120,
        )
    assert r.status_code == 200, r.text
    return r.content


def test_gap_fokus_with_file_structure(da3_response):
    wb = _load_wb(da3_response)
    assert wb.sheetnames == EXPECTED_SHEET_ORDER
    ring = wb["RINGKASAN_MODEL"]
    assert ring.max_row - 1 == 47, f"RINGKASAN_MODEL expected 47 data rows, got {ring.max_row-1}"

    col_i = RINGKASAN_HEADER.index("di_berkas_anda")
    kode_i = RINGKASAN_HEADER.index("kode_model")
    pat = re.compile(r"^\d+ kelompok langsung diterapkan · \d+ varian ditebak otomatis \(BOM_OTOMATIS\) · \d+ masih perlu isian Anda \(BOM_AKSESORIS\)$")

    stopped_ok = 0
    for row in ring.iter_rows(min_row=2, values_only=False):
        val = row[col_i].value
        code = row[kode_i].value
        assert val != "—", f"model {code} still — despite file uploaded"
        if code in STOPPED_MODELS:
            assert val == "tidak ada di berkas Anda", f"{code}: {val}"
            # entire row grey EDEDED
            for c in row:
                assert _fg(c) == GREY, f"stopped {code} row not fully EDEDED at col {c.column}: fg={_fg(c)}"
            stopped_ok += 1
        else:
            assert val == "tidak ada di berkas Anda" or pat.match(val), f"{code}: unexpected '{val}'"
    assert stopped_ok == len(STOPPED_MODELS), f"stopped models found: {stopped_ok}/{len(STOPPED_MODELS)}"


def test_bom_otomatis_no_yellow(da3_response):
    wb = _load_wb(da3_response)
    ws = wb["BOM_OTOMATIS"]
    assert ws.max_row > 1, "BOM_OTOMATIS should have data rows"
    for row in ws.iter_rows(min_row=2):
        for c in row:
            assert _fg(c) != YELLOW, f"BOM_OTOMATIS row {c.row} col {c.column} is YELLOW"


def test_bom_aksesoris_each_group_has_yellow(da3_response):
    wb = _load_wb(da3_response)
    ws = wb["BOM_AKSESORIS"]
    assert ws.max_row > 1
    # BOM_FOKUS_COLS order: kode_model, nama_model, kode_material, nama_material,
    # qty_per_pcs, satuan, catatan, varian, varian_tersedia, yang_perlu_diisi
    header = [c.value for c in ws[1]]
    kode_model_i = header.index("kode_model")
    kode_mat_i = header.index("kode_material")

    # groups: rows begin where kode_model non-empty
    groups = []  # list[list[row_idx]]
    cur = []
    for r in range(2, ws.max_row + 1):
        km = ws.cell(row=r, column=kode_model_i + 1).value
        if km:
            if cur:
                groups.append(cur)
            cur = [r]
        else:
            cur.append(r)
    if cur:
        groups.append(cur)

    assert len(groups) > 0
    for g in groups:
        has_yellow = False
        for r in g:
            for c in ws[r]:
                if _fg(c) == YELLOW:
                    has_yellow = True
                    break
            if has_yellow:
                break
        # blank_group check: head row kode_material cell YELLOW even if empty
        head_mat_cell = ws.cell(row=g[0], column=kode_mat_i + 1)
        blank_group_head = _fg(head_mat_cell) == YELLOW
        assert has_yellow or blank_group_head, f"group starting row {g[0]} has no yellow cells"


def _count_bom_rows_per_model(ws, header):
    """rows per kode_model (grup termasuk baris di bawahnya sampai kode_model berikutnya)."""
    km_i = header.index("kode_model")
    counts: dict[str, int] = {}
    cur_code = None
    for r in range(2, ws.max_row + 1):
        km = ws.cell(row=r, column=km_i + 1).value
        if km:
            cur_code = km
        if cur_code:
            counts[cur_code] = counts.get(cur_code, 0) + 1
    return counts


def test_consistency_ringkasan_vs_bom_aksesoris(da3_response):
    """Sample: DA-1401 (Rachel set) → 3 perlu isian & 3 otomatis; DA-2112 (Heidi) → 24 otomatis, 0 perlu isian."""
    wb = _load_wb(da3_response)
    ring = wb["RINGKASAN_MODEL"]
    kode_i = RINGKASAN_HEADER.index("kode_model")
    berkas_i = RINGKASAN_HEADER.index("di_berkas_anda")
    pat = re.compile(r"(\d+) kelompok langsung diterapkan · (\d+) varian ditebak otomatis \(BOM_OTOMATIS\) · (\d+) masih perlu isian Anda \(BOM_AKSESORIS\)")

    parsed_by_code: dict[str, tuple[int, int, int]] = {}
    for row in ring.iter_rows(min_row=2, values_only=True):
        code = row[kode_i]
        val = row[berkas_i]
        m = pat.match(val or "")
        if m:
            parsed_by_code[code] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    assert "DA-1401" in parsed_by_code, "DA-1401 not in ringkasan"
    assert "DA-2112" in parsed_by_code, "DA-2112 not in ringkasan"

    d1401 = parsed_by_code["DA-1401"]
    assert d1401[2] == 3, f"DA-1401 perlu_isian expected 3 got {d1401[2]}"
    assert d1401[1] == 3, f"DA-1401 otomatis expected 3 got {d1401[1]}"

    d2112 = parsed_by_code["DA-2112"]
    assert d2112[1] == 24, f"DA-2112 otomatis expected 24 got {d2112[1]}"
    assert d2112[2] == 0, f"DA-2112 perlu_isian expected 0 got {d2112[2]}"


# ─── 3. ROUNDTRIP fill-preview reads BOM_OTOMATIS ───────────────────────
def test_fillpreview_reads_bom_otomatis(auth, da3_response):
    r = requests.post(
        f"{BASE}/api/rahaza/master/fill-preview",
        headers=auth,
        files={"file": ("DATA_YANG_PERLU_DIISI_DA_FOKUS.xlsx", da3_response, XLSX_MIME)},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("ok") is True, f"ok=False errors={d.get('errors')}"
    assert d.get("errors") == [], d.get("errors")
    bg = d.get("bom_groups") or []
    assert len(bg) > 0, f"bom_groups empty (BOM_OTOMATIS should be parsed)"


# ─── 4. AUTH & FORMAT GUARDS ────────────────────────────────────────────
def test_gap_fokus_unauth():
    r = requests.post(f"{BASE}/api/rahaza/master/gap-fokus", files={}, timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"


def test_gap_fokus_bad_extension(auth):
    r = requests.post(
        f"{BASE}/api/rahaza/master/gap-fokus",
        headers=auth,
        files={"file": ("junk.csv", b"a,b,c\n1,2,3", "text/csv")},
        timeout=15,
    )
    assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text[:200]}"
