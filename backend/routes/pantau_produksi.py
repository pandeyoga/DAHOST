"""routes/pantau_produksi.py — API layar Pantau Produksi & Laporan Selisih (Tahap 9, 7 Nov 2026).

Satu layar yang sama di Portal Produksi dan Portal Maklon (keputusan owner no. 7). Semua angka dari
`core.pantau_produksi` (per baris PO) — tab hanya menjumlah. BACA SAJA: tidak ada endpoint tulis.

Prefix /api/pantau — setiap endpoint WAJIB menerima `business_type` (internal | maklon):
  GET /ringkasan            alur barang, keseimbangan (PO penyebab), telat, selesai, deadline ≤14 hari, seri dobel
  GET /vendor               per vendor CMT (+ job & QC per job)
  GET /po                   per PO (+ seri → SKU), cari PO/vendor/seri/SKU, saring status
  GET /kejar                papan Kejar CMT (internal & maklon)
  GET /kiriman              kiriman potongan ke CMT: dikirim / diterima / kurang per batch
  GET /kapasitas            beban (internal + maklon) vs kapasitas + laju setor
  GET /kapasitas/cek        cek order baru muat atau tidak (qty, target hari)
  GET /selisih              Laporan Selisih otomatis per baris PO
  GET /selisih/vendor       laporan selisih yang diisi vendor
  GET /selisih/klien        kirim ke klien vs diterima klien (maklon; belum dikonfirmasi dipisah)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import require_auth, serialize_doc
from core import pantau_produksi as pp
from database import get_db
from routes.production_rbac import deny_klien, is_vendor

router = APIRouter(prefix="/api/pantau", tags=["pantau-produksi"])

BT = Query(..., pattern="^(internal|maklon)$", description="internal = Portal Produksi, maklon = Portal Maklon")


async def _staff(request: Request) -> dict:
    """Layar staf DA: klien & vendor CMT ditolak (vendor memakai Portal Vendor)."""
    user = await require_auth(request)
    deny_klien(user)
    if is_vendor(user):
        raise HTTPException(403, "Layar Pantau Produksi hanya untuk staf DA — vendor memakai Portal Vendor.")
    return user


def _scope_running(scope: str) -> Optional[bool]:
    return None if scope == "all" else True


@router.get("/ringkasan")
async def get_ringkasan(request: Request, business_type: str = BT, days: int = Query(7, ge=1, le=90)):
    await _staff(request)
    return serialize_doc(await pp.ringkasan(get_db(), business_type, days=days))


@router.get("/vendor")
async def get_per_vendor(request: Request, business_type: str = BT,
                         scope: str = Query("running", pattern="^(running|all)$")):
    await _staff(request)
    return serialize_doc(await pp.per_vendor(get_db(), business_type, running=_scope_running(scope)))


@router.get("/po")
async def get_per_po(request: Request, business_type: str = BT, search: str = Query("", max_length=80),
                     status: str = Query("", pattern="^(|belum|jalan|selesai|ditutup)$"),
                     scope: str = Query("running", pattern="^(running|all)$")):
    await _staff(request)
    return serialize_doc(await pp.per_po(get_db(), business_type, search=search, state=status,
                                         running=_scope_running(scope)))


@router.get("/kejar")
async def get_kejar(request: Request, business_type: str = BT,
                    scope: str = Query("running", pattern="^(running|all)$"),
                    bucket: str = Query("", pattern="^(|telat|jatuh_tempo|mendekati|on_track|aman|tanpa_deadline)$")):
    await _staff(request)
    from services.cmt_kejar import list_kejar
    res = await list_kejar(get_db(), scope=scope, business_type=business_type)
    counts: dict = {}
    for r in res["rows"]:
        counts[r["bucket"]] = counts.get(r["bucket"], 0) + 1
    rows = [r for r in res["rows"] if not bucket or r["bucket"] == bucket]
    return serialize_doc({**res, "rows": rows, "count": len(rows), "bucket_counts": counts, "total": len(res["rows"])})


@router.get("/kiriman")
async def get_kiriman(request: Request, business_type: str = BT, po_id: str = Query("", max_length=80)):
    await _staff(request)
    from services.cmt_intake import intake_batches
    return serialize_doc(await intake_batches(get_db(), po_id=po_id or None, scope=business_type))


@router.get("/kapasitas")
async def get_kapasitas(request: Request, business_type: str = BT, window_days: int = Query(30, ge=7, le=180)):
    await _staff(request)
    return serialize_doc(await pp.capacity(get_db(), business_type, window_days=window_days))


@router.get("/kapasitas/cek")
async def get_cek_order(request: Request, business_type: str = BT, qty: int = Query(..., ge=1, le=1_000_000),
                        target_days: int = Query(14, ge=1, le=365), vendor_id: str = Query("", max_length=80),
                        window_days: int = Query(30, ge=7, le=180)):
    await _staff(request)
    cap = await pp.capacity(get_db(), business_type, window_days=window_days)
    return pp.check_new_order(cap, qty, target_days, vendor_id)


def _period(date_from: str, date_to: str) -> tuple[str, str]:
    import re
    rx = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for v in (date_from, date_to):
        if v and not rx.match(v):
            raise HTTPException(400, "Format tanggal harus TTTT-BB-HH.")
    return date_from or "", date_to or ""


@router.get("/selisih")
async def get_selisih(request: Request, business_type: str = BT, date_from: str = Query("", alias="from"),
                      date_to: str = Query("", alias="to"), vendor_id: str = Query("", max_length=80),
                      po_id: str = Query("", max_length=80), only_diff: bool = False):
    await _staff(request)
    f, t = _period(date_from, date_to)
    return serialize_doc(await pp.selisih(get_db(), business_type, date_from=f, date_to=t, vendor_id=vendor_id,
                                          po_id=po_id, only_diff=only_diff))


@router.get("/selisih/vendor")
async def get_selisih_vendor(request: Request, business_type: str = BT, date_from: str = Query("", alias="from"),
                             date_to: str = Query("", alias="to"), vendor_id: str = Query("", max_length=80),
                             po_id: str = Query("", max_length=80)):
    await _staff(request)
    f, t = _period(date_from, date_to)
    return serialize_doc(await pp.vendor_reports(get_db(), business_type, date_from=f, date_to=t,
                                                 vendor_id=vendor_id, po_id=po_id))


@router.get("/selisih/klien")
async def get_selisih_klien(request: Request, business_type: str = BT, date_from: str = Query("", alias="from"),
                            date_to: str = Query("", alias="to"), vendor_id: str = Query("", max_length=80),
                            po_id: str = Query("", max_length=80)):
    await _staff(request)
    f, t = _period(date_from, date_to)
    rows = await pp.buyer_receipt_rows(get_db(), business_type, po_id=po_id, vendor_id=vendor_id,
                                       date_from=f, date_to=t)
    tot = {k: sum(r[k] for r in rows) for k in ("total_shipped", "total_received", "total_unconfirmed",
                                                 "total_variance", "qty_short_open")}
    return serialize_doc({"count": len(rows), "rows": rows, "summary": tot})
