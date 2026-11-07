"""routes/rahaza_journal_import — Impor pencatatan/penjurnalan dari Excel (core.journal_import)."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import log_activity
from core import journal_import as ji
from database import get_db
from routes.rahaza_coa import _require_fin

router = APIRouter(prefix="/api/rahaza/finance/journal-import", tags=["rahaza-journal-import"])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Berkas kosong.")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Hanya berkas .xlsx (unduh template dulu).")
    return data


@router.get("/template")
async def template(request: Request):
    await _require_fin(request)
    data = await ji.build_template(get_db())
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX,
                             headers={"Content-Disposition": 'attachment; filename="IMPOR_JURNAL.xlsx"'})


@router.post("/preview")
async def preview(request: Request, file: UploadFile = File(...)):
    await _require_fin(request)
    from core.entities import entity_from_request
    ent = entity_from_request(request)   # Tahap 8: buku CV tujuan impor
    res = await ji.parse_workbook(get_db(), await _read(file), ent)
    res["filename"] = file.filename
    res["entity"] = ent
    return res


@router.post("/apply")
async def apply(request: Request, file: UploadFile = File(...)):
    user = await _require_fin(request)
    db = get_db()
    from core.entities import entity_from_request
    ent = entity_from_request(request)   # Tahap 8: buku CV tujuan impor (Gabungan ditolak)
    res = await ji.parse_workbook(db, await _read(file), ent)
    if not res["ok"]:
        raise HTTPException(400, {"message": "Berkas belum lolos pemeriksaan — perbaiki dulu.", "errors": res["errors"]})
    if not res["journals"]:
        return {"ok": True, "posted_count": 0, "failed_count": 0, "posted": [], "failed": [],
                "skipped_existing": res["skipped_existing"], "message": "Tidak ada jurnal baru (semua baris sudah pernah diimpor)."}
    out = await ji.post_journals(db, user, res["journals"], file.filename or "upload", ent)
    await log_activity(user["id"], user.get("name", ""), "import_journals", "journal",
                       f"{file.filename}: {out['posted_count']} terposting, {out['failed_count']} gagal")
    return {"ok": out["failed_count"] == 0, "skipped_existing": res["skipped_existing"], **out}
