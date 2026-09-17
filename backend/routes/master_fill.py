"""Jalan pintas pengisian master: salin BOM ke varian, tambah aksesoris massal, template Harga·Satuan·Rekening, HPP standar."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import log_activity
from core import master_fill as mf
from database import get_db
from routes.rahaza_coa import _require_fin

router = APIRouter(prefix="/api/rahaza/master", tags=["master-fill"])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Berkas harus .xlsx (template dari layar ini).")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Berkas terlalu besar (maks 8 MB).")
    return data


@router.post("/bom/copy-missing")
async def bom_copy_missing(request: Request):
    user = await _require_fin(request)
    body = await request.json() if (request.headers.get("content-length") or "0") != "0" else {}
    res = await mf.bom_copy_to_missing(get_db(), user, body.get("model_id"))
    await log_activity(user["id"], user.get("name", ""), "bom_copy_missing", "rahaza.bom", f"{res['created']} BOM baru")
    return res


@router.post("/bom/add-lines")
async def bom_add_lines(request: Request):
    user = await _require_fin(request)
    body = await request.json()
    if not body.get("model_id") or not body.get("lines"):
        raise HTTPException(400, "model_id & lines wajib diisi.")
    res = await mf.bom_add_lines_to_model(get_db(), user, body["model_id"], body["lines"])
    await log_activity(user["id"], user.get("name", ""), "bom_add_lines", "rahaza.bom", f"{body['model_id']} +{res['lines_appended']}")
    return res


@router.get("/fill-template")
async def fill_template(request: Request):
    await _require_fin(request)
    data = await mf.build_fill_template(get_db())
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX, headers={"Content-Disposition": 'attachment; filename="TEMPLATE_HARGA_SATUAN_REKENING.xlsx"'})


@router.get("/gap-workbook")
async def gap_workbook(request: Request):
    """Satu Excel berisi SEMUA data yang masih harus diisi (baris sudah terisi model/SKU/material/akun)."""
    await _require_fin(request)
    from core.gap_workbook import build_gap_workbook
    data, _stats = await build_gap_workbook(get_db())
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX,
                             headers={"Content-Disposition": 'attachment; filename="DATA_YANG_PERLU_DIISI_DA.xlsx"'})


@router.post("/gap-workbook")
async def gap_workbook_sisa(request: Request, file: UploadFile | None = File(None)):
    """Berkas isian BERIKUTNYA: dibangun dari berkas klien (kelompok BOM yang dilewati ditulis ulang utuh + VARIAN_BARU + MATERIAL isi kemasan)."""
    await _require_fin(request)
    from core.gap_workbook import build_gap_workbook
    db = get_db()
    data = await _read(file) if file is not None and file.filename else None
    parsed = await mf.parse_fill_workbook(db, data) if data else None
    out, _stats = await build_gap_workbook(db, parsed, data)
    name = "DATA_YANG_PERLU_DIISI_DA_SISA.xlsx" if parsed else "DATA_YANG_PERLU_DIISI_DA.xlsx"
    return StreamingResponse(io.BytesIO(out), media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/fill-preview")
async def fill_preview(request: Request, file: UploadFile = File(...)):
    await _require_fin(request)
    return await mf.parse_fill_workbook(get_db(), await _read(file))


@router.post("/fill-apply")
async def fill_apply(request: Request, file: UploadFile = File(...), scope: str = "all"):
    """scope=bom → hanya sheet BOM_AKSESORIS diterapkan; kesalahan sheet lain tidak menghalangi."""
    user = await _require_fin(request)
    db = get_db()
    data = await _read(file)
    parsed = await mf.parse_fill_workbook(db, data)
    if scope != "bom" and not parsed["ok"]:
        raise HTTPException(400, {"message": "Berkas belum lolos pemeriksaan.", "errors": parsed["errors"]})
    var_res = {"variants_created": 0, "variants_created_skus": []}
    if parsed.get("new_variants"):
        from core.gap_workbook import apply_new_variants
        var_res = await apply_new_variants(db, parsed["new_variants"], user)
        parsed = await mf.parse_fill_workbook(db, data)  # kelompok BOM model yang baru punya varian kini ikut diterapkan
    res = await mf.apply_fill(db, parsed, user, scope="bom" if scope == "bom" else "all")
    res.update(var_res)
    await log_activity(user["id"], user.get("name", ""), "fill_apply", "master", f"scope={res['scope']} " + str(res)[:280])
    return res


@router.post("/laporan-sisa")
async def laporan_sisa(request: Request, file: UploadFile | None = File(None)):
    """LAPORAN_SISA_DA.xlsx — kekurangan yang tidak diimpor (dari berkas unggahan bila ada + kondisi DB). Tidak mengubah data."""
    await _require_fin(request)
    from core.laporan_sisa import build_laporan_sisa
    db = get_db()
    data = await _read(file) if file is not None and file.filename else None
    parsed = await mf.parse_fill_workbook(db, data) if data else None
    out, _summary = await build_laporan_sisa(db, parsed, data)
    return StreamingResponse(io.BytesIO(out), media_type=_XLSX, headers={"Content-Disposition": 'attachment; filename="LAPORAN_SISA_DA.xlsx"'})


@router.post("/recalc-hpp")
async def recalc_hpp(request: Request):
    user = await _require_fin(request)
    return await mf.recalc_standard_costs(get_db(), user)
