"""Iter130: BOM_AKSESORIS + BOM_OTOMATIS round-trip via API (per review request iter130).

Menjalankan seluruh alur endpoint berkas FOKUS + preview + apply + gap-workbook.
Login dilakukan sekali (rate-limit 10/60s). Setelah fill-apply, DB DIRESTORE oleh
script pemanggil (bukan test) sesuai instruksi.
"""
import io
import os
import subprocess

import openpyxl
import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0].strip()
).rstrip("/")


@pytest.fixture(scope="module")
def token():
    tokp = "/tmp/tok"
    if os.path.exists(tokp) and open(tokp).read().strip():
        return open(tokp).read().strip()
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@garment.com", "password": "Admin@123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    open(tokp, "w").write(tok)
    return tok


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


def _post(path, H, data=None, **params):
    files = (
        {"file": ("x.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        if data
        else None
    )
    r = requests.post(f"{BASE_URL}{path}", headers=H, files=files, params=params, timeout=180)
    return r


# --- 1. FOKUS tanpa file ---
@pytest.fixture(scope="module")
def fokus_empty(H):
    r = _post("/api/rahaza/master/gap-fokus", H)
    assert r.status_code == 200, r.text[:400]
    return r.content


def test_fokus_empty_sheetnames_and_bom_otomatis_header(fokus_empty):
    wb = openpyxl.load_workbook(io.BytesIO(fokus_empty))
    expected = ["PETUNJUK", "VARIAN_BARU", "BOM_AKSESORIS", "BOM_OTOMATIS", "MATERIAL", "REF_AKSESORIS"]
    assert wb.sheetnames == expected, wb.sheetnames

    ws_oto = wb["BOM_OTOMATIS"]
    hdr = [c.value for c in ws_oto[1]]
    expected_hdr = [
        "kode_model",
        "nama_model",
        "kode_material",
        "nama_material",
        "qty_per_pcs",
        "satuan",
        "keterangan",
        "varian",
        "varian_tersedia",
        "yang_perlu_diisi",
    ]
    assert hdr == expected_hdr, hdr
    # Hanya header (max_row == 1) di FOKUS tanpa file
    assert ws_oto.max_row == 1, f"BOM_OTOMATIS harus hanya header, ada {ws_oto.max_row} baris"


def test_petunjuk_mentions_bom_otomatis(fokus_empty):
    wb = openpyxl.load_workbook(io.BytesIO(fokus_empty))
    txt = "\n".join(str(c.value) for row in wb["PETUNJUK"].iter_rows() for c in row if c.value)
    assert "BOM_OTOMATIS" in txt, "PETUNJUK harus menyebut BOM_OTOMATIS"


# --- 2. Bangun berkas uji sesuai spek iter130: 2 baris di masing-masing sheet ---
@pytest.fixture(scope="module")
def uji_xlsx(fokus_empty):
    wb = openpyxl.load_workbook(io.BytesIO(fokus_empty))
    ref = list(wb["REF_AKSESORIS"].iter_rows(values_only=True, min_row=2))
    acc = [r for r in ref if r[4] and float(r[4]) > 0 and (r[3] or "").lower() == "pcs"]
    assert acc, "butuh minimal 1 ACC pcs berharga di REF_AKSESORIS"
    acc1 = acc[0][0]

    aks_rows = [r for r in wb["BOM_AKSESORIS"].iter_rows(values_only=True, min_row=2) if r[0]]
    models = sorted({r[0] for r in aks_rows})
    assert len(models) >= 2, f"butuh 2 model tanpa aksesoris, ada {len(models)}"
    MODEL_A, MODEL_B = models[0], models[1]

    up = openpyxl.Workbook()
    w1 = up.active
    w1.title = "BOM_AKSESORIS"
    hdr9 = [
        "kode_model",
        "nama_model",
        "kode_material",
        "nama_material",
        "qty_per_pcs",
        "satuan",
        "keterangan",
        "varian",
        "varian_tersedia",
    ]
    w1.append(hdr9)
    w1.append([MODEL_A, "", acc1, "", "1 pcs", "", "", "", ""])
    w1.append(["", "", "KODE-TIDAK-ADA-XYZ", "", 1, "pcs", "", "", ""])
    w2 = up.create_sheet("BOM_OTOMATIS")
    w2.append(hdr9)
    w2.append([MODEL_B, "", acc1, "", "2 pcs", "", "", "", ""])
    w2.append(["", "", "KODE-TIDAK-ADA-ABC", "", 1, "pcs", "", "", ""])
    buf = io.BytesIO()
    up.save(buf)
    return {"data": buf.getvalue(), "model_a": MODEL_A, "model_b": MODEL_B, "acc1": acc1}


# --- 3. fill-preview ---
def test_fill_preview(H, uji_xlsx):
    r = _post("/api/rahaza/master/fill-preview", H, data=uji_xlsx["data"])
    assert r.status_code == 200, r.text[:400]
    p = r.json()
    print("totals:", p["totals"])
    print("warnings:", p["warnings"])
    assert p["totals"]["bom_lines"] == 2, p["totals"]
    assert p["totals"]["bom_groups"] == 2, p["totals"]
    assert p["totals"]["bom_models"] == 2, p["totals"]
    groups = {g["model_code"] for g in p["bom_groups"]}
    assert groups == {uji_xlsx["model_a"], uji_xlsx["model_b"]}, groups
    assert any(w.startswith("BOM_AKSESORIS baris 3:") for w in p["warnings"]), p["warnings"]
    assert any(w.startswith("BOM_OTOMATIS baris 3:") for w in p["warnings"]), p["warnings"]
    assert all("where" in i for i in p["bom_issues"]), p["bom_issues"]


# --- 4. gap-fokus DENGAN file uji ---
def test_gap_fokus_with_file(H, uji_xlsx):
    r = _post("/api/rahaza/master/gap-fokus", H, data=uji_xlsx["data"])
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    rows_aks = list(wb["BOM_AKSESORIS"].iter_rows(min_row=2))
    codes = {r[2].value for r in rows_aks}
    assert "KODE-TIDAK-ADA-XYZ" in codes and "KODE-TIDAK-ADA-ABC" in codes, codes
    # kelompok bermasalah ditulis utuh; cek warna kuning FFF2CC pada sel kode_material
    yellow_cells = [r[2] for r in rows_aks if r[2].value in ("KODE-TIDAK-ADA-XYZ", "KODE-TIDAK-ADA-ABC")]
    for c in yellow_cells:
        rgb = getattr(c.fill.fgColor, "rgb", "") or ""
        assert rgb.endswith("FFF2CC"), f"kode_material harus kuning FFF2CC, dapat {rgb}"
    # MODEL_A / MODEL_B hanya 1x sebagai kepala kelompok
    ma = sum(1 for r in rows_aks if r[0].value == uji_xlsx["model_a"])
    mb = sum(1 for r in rows_aks if r[0].value == uji_xlsx["model_b"])
    assert ma == 1, f"MODEL_A harus 1 kepala kelompok, {ma}"
    assert mb == 1, f"MODEL_B harus 1 kepala kelompok, {mb}"


# --- 5. gap-workbook (Laporan SISA) DENGAN file uji ---
def test_gap_workbook_reads_bom_otomatis(H, uji_xlsx):
    r = _post("/api/rahaza/master/gap-workbook", H, data=uji_xlsx["data"])
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    sisa = [row for row in wb["BOM_AKSESORIS"].iter_rows(values_only=True, min_row=2)]
    assert any(r[2] == "KODE-TIDAK-ADA-ABC" for r in sisa), "kelompok BOM_OTOMATIS harus ikut Laporan SISA"


# --- 6. fill-apply (idempoten) + restore DB ---
def test_fill_apply_idempotent_and_restore(H, uji_xlsx):
    try:
        r1 = _post("/api/rahaza/master/fill-apply", H, data=uji_xlsx["data"], scope="bom")
        assert r1.status_code == 200, r1.text[:400]
        a1 = r1.json()
        print("apply#1:", {k: a1.get(k) for k in ("bom_models", "bom_groups", "boms_touched", "boms_unchanged")})
        assert a1["bom_models"] == 2, a1
        assert a1["boms_touched"] > 0, a1

        r2 = _post("/api/rahaza/master/fill-apply", H, data=uji_xlsx["data"], scope="bom")
        assert r2.status_code == 200
        a2 = r2.json()
        print("apply#2:", {k: a2.get(k) for k in ("boms_touched", "boms_unchanged")})
        assert a2["boms_touched"] == 0, a2
        assert a2["boms_unchanged"] == a1["boms_touched"] + a1["boms_unchanged"], (a1, a2)
    finally:
        # KEMBALIKAN DB seed apa pun hasilnya
        cmd = [
            "mongorestore",
            "--gzip",
            "--archive=/app/seed/DA_SEED_GOLIVE.archive.gz",
            "--nsFrom=dahost_erp.*",
            "--nsTo=test_database.*",
            "--drop",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        print("restore rc:", p.returncode, "stderr tail:", p.stderr[-400:])
        assert p.returncode == 0, p.stderr[-800:]
